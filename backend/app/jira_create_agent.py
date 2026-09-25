from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import HTTPException

from .connection_models import JiraConnectionConfig
from .jira_create_agent_conversation import (
    build_pending_fields,
    build_requirement_update_context,
    extract_followup_field_updates,
    has_requirement_baseline,
    is_requirement_modification,
    looks_like_field_mutation,
    merge_field_patch,
    merge_preserving_requirement,
    response_conversation_phase,
    should_use_field_patch_path,
)
from .jira_create_agent_preprocess import (
    LinkedWorkItemIntent,
    format_preprocessed_for_llm,
    preprocess_user_message,
)
from .jira_create_agent_resolve import resolve_agent_fields, resolve_linked_work_items
from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS
from .jira_create_models import CreateJiraAgentRequest, CreateJiraAgentResponse, JiraCreateMetadata, MissingRequiredField
from .jira_create_validation import extract_json_object, field_is_empty, missing_required_fields
from .llm import LLMProvider

logger = logging.getLogger(__name__)

AGENT_RULES = """
You are the Create Jira Agent for AIDLC Studio.
Transform the REQUIREMENT into Jira Summary and Description. USER-PROVIDED JIRA FIELDS are listed separately — never repeat them in Summary or Description.

Rules:
1. Never invent Assignee, Priority, Sprint, Reporter, dates, labels, parent, story points, linked work items, or other factual Jira values.
2. Summary: exactly one concise line derived only from the requirement (never assignee, priority, sprint, labels, dates, parent, story points, linked work items, or other Jira metadata).
3. Description: exactly two logical sections as JSON strings — "solution" and "acceptanceCriteria" — requirement and expected behavior only. Never include Jira field assignments or values.
4. Put only explicitly user-provided Jira field values in "fields" using field ids or labels from the schema. Do not invent values.
5. Put linked work item relationship and target intents in "linkedWorkItems". Never put them in Description.
6. Do not create Jira issues; only propose field values for human review.
7. Output JSON only. Use one of these modes:
INITIAL (first requirement only):
{
  "mode": "initial_requirement",
  "summary": "...",
  "description": { "solution": "...", "acceptanceCriteria": "..." },
  "fields": { "<field-id-or-label>": "<value>" },
  "linkedWorkItems": [ { "relationshipIntent": "...", "targetIntent": "..." } ],
  "clarification": null
}
FOLLOW-UP field-only updates (application handles these without calling you):
{
  "mode": "field_update",
  "fieldUpdates": { "<field-id-or-label>": "<value>" },
  "clarification": null
}
REQUIREMENT CHANGE (only when user explicitly changes functional requirement behavior):
{
  "mode": "requirement_update",
  "summary": "...",
  "description": { "solution": "...", "acceptanceCriteria": "..." },
  "fieldUpdates": { "<field-id-or-label>": "<value>" },
  "linkedWorkItems": [ { "relationshipIntent": "...", "targetIntent": "..." } ],
  "clarification": null
}
8. Use field ids from the schema when possible for "fields" keys.
9. Project and Issue Type are already selected — never ask for them.
10. If something about the requirement (not a Jira field) is genuinely unclear, set "clarification" to a short question; otherwise null.
"""

_AGENT_SKIPPABLE_REQUIRED = {"summary", "description"}

_JIRA_FIELD_LEAK_RE = re.compile(
    r"(?i)\b("
    r"assignee|assigned to|priority|\blabels\b|active sprint|future sprint|\bsprint\b|"
    r"start date|due date|parent(?:\s+(?:jira|issue))?|story points?|"
    r"linked work items?|linked as|clone[sd]? of|reporter"
    r")\b"
)


def build_schema_prompt(metadata: JiraCreateMetadata) -> str:
    fields: list[dict[str, Any]] = []
    for field in metadata.fields.values():
        if field.id in CONTEXT_MANAGED_FIELD_IDS:
            continue
        entry: dict[str, Any] = {
            "id": field.id,
            "label": field.label,
            "required": field.required,
            "type": field.type,
            "searchable": field.searchable,
        }
        if field.options:
            entry["options"] = [{"label": option.label, "value": option.value} for option in field.options]
        if field.description:
            entry["description"] = field.description
        fields.append(entry)
    return json.dumps({"project_id": metadata.project_id, "issue_type_id": metadata.issue_type_id, "fields": fields}, indent=2)


def _normalize_summary(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _normalize_description(text: str) -> str:
    parts = [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]
    return "\n\n".join(parts[:2])


def strip_jira_field_intents_from_description(text: str) -> str:
    if not text.strip():
        return text
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        header = re.match(r"(?i)^(solution|acceptance criteria)\s*:(.*)$", stripped)
        if header:
            remainder = header.group(2).strip()
            if remainder and _JIRA_FIELD_LEAK_RE.search(remainder):
                kept.append(f"{header.group(1).title()}:")
            else:
                kept.append(line)
            continue
        if stripped and _JIRA_FIELD_LEAK_RE.search(stripped):
            continue
        kept.append(line)
    collapsed: list[str] = []
    previous_blank = False
    for line in kept:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank
    return "\n".join(collapsed).strip()


def _description_has_body(text: str) -> bool:
    body = re.sub(r"(?i)solution\s*:|acceptance\s+criteria\s*:", "", text)
    return bool(body.strip())


def _default_description_from_requirement(requirement: str) -> str:
    body = requirement.strip()
    return (
        f"Solution:\n{body}\n\n"
        f"Acceptance Criteria:\n"
        f"The described behavior works as specified and existing functionality remains unaffected."
    )


def _field_id_for_llm_key(key: str, metadata: JiraCreateMetadata) -> str | None:
    raw = str(key).strip()
    if not raw:
        return None
    if raw in metadata.fields:
        return raw
    lowered = raw.lower()
    for field_id, field in metadata.fields.items():
        if field_id.lower() == lowered or field.label.strip().lower() == lowered:
            return field_id
    return None


def format_structured_description(description: Any) -> str | None:
    if isinstance(description, str):
        text = description.strip()
        if not text:
            return None
        if re.search(r"(?i)solution\s*:", text) and re.search(r"(?i)acceptance\s+criteria\s*:", text):
            formatted = _normalize_description(text)
        else:
            formatted = _normalize_description(
                f"Solution:\n{text}\n\nAcceptance Criteria:\nVerify the described behavior in the application."
            )
        cleaned = strip_jira_field_intents_from_description(formatted)
        return cleaned or None
    if not isinstance(description, dict):
        return None
    solution = description.get("solution") or description.get("Solution")
    acceptance = description.get("acceptanceCriteria") or description.get("acceptance_criteria") or description.get(
        "acceptance criteria"
    )
    solution_text = strip_jira_field_intents_from_description(str(solution).strip() if solution is not None else "")
    acceptance_text = strip_jira_field_intents_from_description(
        str(acceptance).strip() if acceptance is not None else ""
    )
    if not solution_text and not acceptance_text:
        return None
    if not solution_text:
        solution_text = "Implement the described requirement."
    if not acceptance_text:
        acceptance_text = "Behavior matches the requirement and existing flows continue to work."
    return _normalize_description(f"Solution:\n{solution_text}\n\nAcceptance Criteria:\n{acceptance_text}")


def _normalize_llm_fields(raw_fields: dict[str, Any], metadata: JiraCreateMetadata) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in raw_fields.items():
        field_id = _field_id_for_llm_key(str(key), metadata)
        if not field_id or field_id in CONTEXT_MANAGED_FIELD_IDS:
            continue
        if field_id in normalized and field_is_empty(value):
            continue
        normalized[field_id] = value
    return normalized


def apply_summary_description_fallback(fields: dict[str, Any], requirement: str) -> dict[str, Any]:
    if not requirement.strip():
        return fields
    merged = dict(fields)
    if field_is_empty(merged.get("summary")):
        merged["summary"] = _normalize_summary(requirement)[:255]
    if field_is_empty(merged.get("description")):
        merged["description"] = _normalize_description(_default_description_from_requirement(requirement))
    return merged


def _normalize_linked_work_item_intents(payload: dict[str, Any]) -> list[LinkedWorkItemIntent]:
    source = payload.get("linkedWorkItems") or payload.get("linked_work_items") or payload.get("issue_links")
    if not isinstance(source, list):
        return []
    items: list[LinkedWorkItemIntent] = []
    for raw in source:
        if not isinstance(raw, dict):
            continue
        relationship = str(
            raw.get("relationshipIntent") or raw.get("relationship_intent") or raw.get("relationship") or ""
        ).strip()
        target = str(
            raw.get("targetIntent") or raw.get("target_intent") or raw.get("target") or raw.get("target_issue_key") or ""
        ).strip()
        if not relationship and not target:
            continue
        items.append(LinkedWorkItemIntent(relationship_intent=relationship, target_intent=target))
    return items


def parse_agent_llm_payload(payload: dict[str, Any], metadata: JiraCreateMetadata) -> dict[str, Any]:
    mode = str(payload.get("mode") or "").strip().lower()
    linked_work_items = _normalize_linked_work_item_intents(payload)
    if mode in {"field_resolution", "field_update"}:
        field_updates = payload.get("fieldUpdates") if isinstance(payload.get("fieldUpdates"), dict) else {}
        return {
            "fields": _normalize_llm_fields(field_updates, metadata),
            "clarification": payload.get("clarification"),
            "lock_summary_description": True,
            "linked_work_items": linked_work_items,
        }

    raw_fields: dict[str, Any] = {}
    if isinstance(payload.get("fields"), dict):
        raw_fields.update(payload["fields"])
    if isinstance(payload.get("fieldUpdates"), dict):
        raw_fields.update(payload["fieldUpdates"])

    if mode in {"initial_requirement", "requirement_update"} or "summary" in payload or "description" in payload or raw_fields:
        fields: dict[str, Any] = _normalize_llm_fields(raw_fields, metadata)
        summary = payload.get("summary")
        description = payload.get("description")
        if isinstance(summary, str) and summary.strip():
            fields["summary"] = _normalize_summary(summary)
        formatted_description = format_structured_description(description)
        if formatted_description:
            fields["description"] = formatted_description
        return {
            "fields": fields,
            "clarification": payload.get("clarification"),
            "lock_summary_description": mode == "requirement_update" and not payload.get("summary") and not payload.get("description"),
            "linked_work_items": linked_work_items,
        }

    legacy_fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    return {
        "fields": dict(legacy_fields),
        "clarification": payload.get("message") or payload.get("clarification"),
        "lock_summary_description": False,
        "linked_work_items": linked_work_items,
    }


def validate_agent_payload(payload: dict[str, Any], metadata: JiraCreateMetadata) -> CreateJiraAgentResponse:
    parsed = parse_agent_llm_payload(payload, metadata)
    raw_fields = parsed["fields"] if isinstance(parsed.get("fields"), dict) else {}
    known = set(metadata.fields.keys())
    fields: dict[str, Any] = {}
    for field_id, value in raw_fields.items():
        field_key = str(field_id)
        if field_key not in known or field_key in CONTEXT_MANAGED_FIELD_IDS:
            continue
        field = metadata.fields[field_key]
        if field.type in {"select", "radio", "status", "priority", "parent", "color-picker"} and field.options:
            allowed = {option.value for option in field.options}
            if str(value) not in allowed:
                fields[field_key] = value
                continue
        if field.type == "checkbox" and field.options:
            allowed = {option.value for option in field.options}
            if isinstance(value, list):
                fields[field_key] = [str(item) for item in value if str(item) in allowed]
            elif str(value) in allowed:
                fields[field_key] = [str(value)]
            continue
        fields[field_key] = value

    missing: list[MissingRequiredField] = []
    clarification = parsed.get("clarification")
    if isinstance(clarification, str) and clarification.strip():
        missing.append(
            MissingRequiredField(
                id="__clarification__",
                label="Clarification",
                question=clarification.strip(),
            )
        )

    return CreateJiraAgentResponse(status="needs_information", message="", fields=fields, missing_required_fields=missing)


def _format_applied_field_updates(
    metadata: JiraCreateMetadata,
    merged_values: dict[str, Any],
    patch_field_ids: set[str],
) -> str | None:
    if not patch_field_ids:
        return None
    updates: list[str] = []
    for field_id in sorted(patch_field_ids):
        field = metadata.fields.get(field_id)
        if not field:
            continue
        value = merged_values.get(field_id)
        if field_is_empty(value):
            continue
        updates.append(f"{field.label} to {value}")
    if not updates:
        return None
    if len(updates) == 1:
        return f"Updated {updates[0]}."
    joined = "; ".join(updates)
    return f"Updated {joined}."


def build_user_facing_message(
    metadata: JiraCreateMetadata,
    request: CreateJiraAgentRequest,
    merged_values: dict[str, Any],
    missing: list[MissingRequiredField],
    *,
    status: str,
    applied_patch_field_ids: set[str] | None = None,
) -> str:
    project = request.project_label or metadata.project_key or "selected project"
    issue_type = request.issue_type_label or metadata.issue_type_name or "selected issue type"
    lines: list[str] = []

    if status == "ready":
        patch_message = _format_applied_field_updates(metadata, merged_values, applied_patch_field_ids or set())
        if patch_message:
            lines.append(patch_message)
        else:
            lines.append("All required Jira fields have values. Review the form on the right and click Create when ready.")
        lines.append("")
        lines.append(f"Context: Project {project} · Issue type {issue_type}")
        return "\n".join(lines)

    drafted = _drafted_field_labels(metadata, merged_values, request.user_edited_field_ids)
    if drafted:
        lines.append("I've updated these Jira fields from your requirement:")
        for label in drafted:
            lines.append(f"✓ {label}")
        lines.append("")

    actionable = [item for item in missing if item.id != "__clarification__"]
    clarification = next((item for item in missing if item.id == "__clarification__"), None)

    if actionable:
        if len(actionable) == 1:
            item = actionable[0]
            lines.append("I still need one more detail before you can create the issue:")
            lines.append("")
            lines.append(f"• {item.label}")
            lines.append(f"  {item.question}")
        else:
            lines.append(f"I still need {len(actionable)} more details before you can create the issue:")
            lines.append("")
            for index, item in enumerate(actionable, start=1):
                lines.append(f"{index}. {item.label}")
                lines.append(f"   {item.question}")
        lines.append("")
        lines.append("Reply with those details and I'll fill the Jira form automatically.")
    elif clarification:
        lines.append(clarification.question)
    else:
        lines.append("Please share any additional details needed for the remaining Jira fields.")

    lines.append("")
    lines.append(f"Context: Project {project} · Issue type {issue_type}")
    return "\n".join(lines)


def _drafted_field_labels(metadata: JiraCreateMetadata, values: dict[str, Any], user_edited: list[str]) -> list[str]:
    edited = set(user_edited)
    labels: list[str] = []
    for field_id, field in metadata.fields.items():
        if field_id in CONTEXT_MANAGED_FIELD_IDS:
            continue
        if field_id in {"summary", "description"} or field_id in edited:
            if not field_is_empty(values.get(field_id)):
                labels.append(field.label)
    return labels


def missing_required_for_agent(
    metadata: JiraCreateMetadata,
    values: dict[str, Any],
    *,
    requirement: str,
) -> list[MissingRequiredField]:
    missing = missing_required_fields(metadata, values)
    if not requirement.strip():
        return missing
    return [item for item in missing if item.id not in _AGENT_SKIPPABLE_REQUIRED]


def enforce_mandatory_fields(
    metadata: JiraCreateMetadata,
    request: CreateJiraAgentRequest,
    response: CreateJiraAgentResponse,
    merged_values: dict[str, Any],
    *,
    requirement: str,
    extra_missing: list[MissingRequiredField] | None = None,
    applied_patch_field_ids: set[str] | None = None,
) -> CreateJiraAgentResponse:
    unresolved = missing_required_for_agent(metadata, merged_values, requirement=requirement)
    combined = unresolved + [item for item in (extra_missing or []) if item.id not in {m.id for m in unresolved}]
    combined += [item for item in response.missing_required_fields if item.id == "__clarification__"]
    status = "ready" if not combined else "needs_information"
    message = build_user_facing_message(
        metadata,
        request,
        merged_values,
        combined,
        status=status,
        applied_patch_field_ids=applied_patch_field_ids,
    )
    phase = response_conversation_phase(status, merged_values)
    pending = build_pending_fields(
        combined,
        prior=request.pending_fields,
        raw_field_values=merged_values,
    )
    return CreateJiraAgentResponse(
        status=status,
        message=message,
        fields=response.fields,
        missing_required_fields=combined,
        pending_clarification_field_id=select_pending_clarification_field(combined),
        conversation_phase=phase,
        pending_fields=pending,
    )


def select_pending_clarification_field(missing: list[MissingRequiredField]) -> str | None:
    actionable = [
        item
        for item in missing
        if item.id not in {"__clarification__", "summary", "description"} and not item.id.startswith("__")
    ]
    if len(actionable) == 1:
        return actionable[0].id
    resolution_failures = [item for item in actionable if "couldn't find" in item.question.lower()]
    if len(resolution_failures) == 1:
        return resolution_failures[0].id
    return None


async def analyze_requirement(
    provider: LLMProvider,
    metadata: JiraCreateMetadata,
    request: CreateJiraAgentRequest,
    config: JiraConnectionConfig,
) -> CreateJiraAgentResponse:
    last_user = next((message.content for message in reversed(request.messages) if message.role == "user"), "")
    requirement_mod = is_requirement_modification(last_user)
    lock_summary_description = False
    preprocessed_requirement = ""
    linked_intents: list[LinkedWorkItemIntent] = []

    patch_field_keys: set[str] = set()
    if should_use_field_patch_path(request, last_user):
        field_updates = extract_followup_field_updates(
            last_user,
            metadata,
            pending_fields=request.pending_fields,
            pending_clarification_field_id=request.pending_clarification_field_id,
        )
        if not field_updates:
            if request.pending_clarification_field_id and request.pending_clarification_field_id in metadata.fields:
                field_updates = {request.pending_clarification_field_id: last_user.strip()}
            elif len(request.pending_fields) == 1:
                field_updates = {request.pending_fields[0].field_id: last_user.strip()}
        if not field_updates and request.pending_fields:
            pending_labels = [
                metadata.fields[item.field_id].label
                for item in request.pending_fields
                if item.field_id in metadata.fields
            ]
            if len(pending_labels) > 1:
                joined = ", ".join(pending_labels)
                return CreateJiraAgentResponse(
                    status="needs_information",
                    message=(
                        f"I still need values for: {joined}.\n\n"
                        f"Please reply with one field value at a time, or name the option exactly "
                        f"(for example a Sprint or Priority label)."
                    ),
                    fields=dict(request.current_values),
                    missing_required_fields=[],
                    pending_clarification_field_id=request.pending_clarification_field_id,
                    conversation_phase="field_resolution",
                    pending_fields=request.pending_fields,
                )
        if not field_updates and looks_like_field_mutation(last_user):
            project = request.project_label or metadata.project_key or "selected project"
            issue_type = request.issue_type_label or metadata.issue_type_name or "selected issue type"
            return CreateJiraAgentResponse(
                status="needs_information",
                message=(
                    "I couldn't tell which Jira field to update from that message. "
                    "Please name the field and value (for example: \"change Story Points to 15\")."
                    f"\n\nContext: Project {project} · Issue type {issue_type}"
                ),
                fields=dict(request.current_values),
                missing_required_fields=[
                    MissingRequiredField(
                        id="__clarification__",
                        label="Clarification",
                        question=(
                            "Which Jira field should I update, and what should the new value be?"
                        ),
                    )
                ],
                pending_clarification_field_id=request.pending_clarification_field_id,
                conversation_phase="field_resolution",
                pending_fields=request.pending_fields,
            )
        patch_field_keys = set(field_updates.keys())
        candidate_fields = dict(request.current_values)
        candidate_fields.update(field_updates)
        validated = CreateJiraAgentResponse(status="needs_information", message="", fields={}, missing_required_fields=[])
        lock_summary_description = True
        preprocessed = preprocess_user_message(last_user, metadata)
        linked_intents = list(preprocessed.linked_work_items)
    else:
        preprocessed = preprocess_user_message(last_user, metadata)
        preprocessed_requirement = preprocessed.requirement
        preprocessed_block = format_preprocessed_for_llm(preprocessed, metadata)
        merged_provided = dict(preprocessed.provided_fields)
        linked_intents = list(preprocessed.linked_work_items)
        conversation_lines: list[str] = []
        for message in request.messages:
            content = message.content
            if message.role == "user" and message.content == last_user:
                content = preprocessed.requirement
            conversation_lines.append(f"{message.role.upper()}: {content}")
        conversation = "\n".join(conversation_lines)
        mode_hint = "requirement_update" if requirement_mod else "initial_requirement"
        requirement_update_block = ""
        if requirement_mod and has_requirement_baseline(request.current_values):
            requirement_update_block = (
                f"{build_requirement_update_context(request, last_user)}\n\n"
            )
        prompt = (
            f"{AGENT_RULES}\n\n"
            f"RESPONSE MODE FOR THIS TURN: {mode_hint}\n\n"
            f"{requirement_update_block}"
            f"JIRA FIELD SCHEMA:\n{build_schema_prompt(metadata)}\n\n"
            f"PREPROCESSED USER INPUT:\n{preprocessed_block}\n\n"
            f"CURRENT FORM VALUES:\n{json.dumps(request.current_values, indent=2)}\n\n"
            f"SELECTED PROJECT: {request.project_label or metadata.project_key or request.project_id}\n"
            f"SELECTED ISSUE TYPE: {request.issue_type_label or metadata.issue_type_name or request.issue_type_id}\n\n"
            f"CONVERSATION:\n{conversation}\n"
        )
        try:
            raw_text = await provider.generate(prompt)
            payload = extract_json_object(raw_text)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("create_jira_agent_failed error=%s", exc)
            raise HTTPException(status_code=502, detail="Create Jira Agent could not analyze the requirement.") from exc

        parsed = parse_agent_llm_payload(payload, metadata)
        validated = validate_agent_payload(payload, metadata)
        lock_summary_description = bool(parsed.get("lock_summary_description"))
        if not linked_intents:
            linked_intents = list(parsed.get("linked_work_items") or [])
        candidate_fields = {**validated.fields, **merged_provided}
        if isinstance(candidate_fields.get("description"), str):
            cleaned = strip_jira_field_intents_from_description(str(candidate_fields["description"]))
            if not _description_has_body(cleaned):
                cleaned = _default_description_from_requirement(preprocessed.requirement)
            candidate_fields["description"] = cleaned
        if mode_hint == "initial_requirement":
            candidate_fields = apply_summary_description_fallback(candidate_fields, preprocessed.requirement)
        elif requirement_mod:
            lock_summary_description = False

    resolved_fields, resolve_missing = await resolve_agent_fields(
        config,
        metadata,
        candidate_fields,
        project_id=request.project_id,
        project_key=metadata.project_key,
    )
    resolved_links, link_missing = await resolve_linked_work_items(
        config,
        linked_intents,
        project_id=request.project_id,
    )

    if patch_field_keys:
        merged = merge_field_patch(
            metadata,
            request.current_values,
            resolved_fields,
            patch_field_keys,
            set(request.user_edited_field_ids),
        )
    else:
        merged = merge_preserving_requirement(
            metadata,
            request.current_values,
            resolved_fields,
            set(request.user_edited_field_ids),
            lock_summary_description=lock_summary_description,
        )
    enforced = enforce_mandatory_fields(
        metadata,
        request,
        validated,
        merged,
        requirement=preprocessed_requirement,
        extra_missing=resolve_missing + link_missing,
        applied_patch_field_ids=patch_field_keys if patch_field_keys else None,
    )
    enforced.fields = merged
    enforced.issue_links = resolved_links
    if enforced.status == "ready":
        enforced.pending_clarification_field_id = None
        enforced.pending_fields = []
        enforced.conversation_phase = "ready_to_create"
    return enforced

