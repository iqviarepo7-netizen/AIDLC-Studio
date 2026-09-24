from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import HTTPException

from .connection_models import JiraConnectionConfig
from .jira_create_agent_preprocess import format_preprocessed_for_llm, preprocess_user_message
from .jira_create_agent_resolve import resolve_agent_fields
from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS
from .jira_create_models import CreateJiraAgentRequest, CreateJiraAgentResponse, JiraCreateMetadata, MissingRequiredField
from .jira_create_validation import extract_json_object, field_is_empty, merge_agent_fields, missing_required_fields
from .llm import LLMProvider

logger = logging.getLogger(__name__)

AGENT_RULES = """
You are the Create Jira Agent for AIDLC Studio.
Transform the REQUIREMENT into Jira Summary and Description. Apply USER-PROVIDED JIRA FIELDS only when explicitly supplied.

Rules:
1. Never invent Assignee, Priority, Sprint, Reporter, dates, client, environment, or other factual Jira values.
2. Summary: exactly one concise line derived only from the requirement.
3. Description: detailed but concise, maximum 2 paragraphs, including requirement/behavior, proposed solution, and Acceptance Criteria in a consistent concise structure.
4. Put only explicitly user-provided Jira field values in "fields" (not Summary/Description).
5. Do not create Jira issues; only propose field values for human review.
6. Output JSON only with this exact shape:
{
  "summary": "...",
  "description": "...",
  "fields": { "<field-id>": "<value>" },
  "clarification": null
}
7. Use field ids exactly as provided in the schema for "fields".
8. Project and Issue Type are already selected — never ask for them.
9. If something is genuinely unclear, set "clarification" to a short question; otherwise null.
"""

_AGENT_SKIPPABLE_REQUIRED = {"summary", "description"}


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


def _default_description_from_requirement(requirement: str) -> str:
    body = requirement.strip()
    return (
        f"Requirement and behavior:\n{body}\n\n"
        f"Proposed solution:\nImplement the described change in the application.\n\n"
        f"Acceptance criteria:\n"
        f"- Behavior matches the requirement\n"
        f"- Change is verified in the UI"
    )


def apply_summary_description_fallback(fields: dict[str, Any], requirement: str) -> dict[str, Any]:
    if not requirement.strip():
        return fields
    merged = dict(fields)
    if field_is_empty(merged.get("summary")):
        merged["summary"] = _normalize_summary(requirement)[:255]
    if field_is_empty(merged.get("description")):
        merged["description"] = _normalize_description(_default_description_from_requirement(requirement))
    return merged


def parse_agent_llm_payload(payload: dict[str, Any], metadata: JiraCreateMetadata) -> dict[str, Any]:
    if "summary" in payload or "description" in payload:
        fields: dict[str, Any] = {}
        if isinstance(payload.get("fields"), dict):
            fields.update(payload["fields"])
        summary = payload.get("summary")
        description = payload.get("description")
        if isinstance(summary, str) and summary.strip():
            fields["summary"] = _normalize_summary(summary)
        if isinstance(description, str) and description.strip():
            fields["description"] = _normalize_description(description)
        return {
            "fields": fields,
            "clarification": payload.get("clarification"),
        }

    legacy_fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    return {
        "fields": dict(legacy_fields),
        "clarification": payload.get("message") or payload.get("clarification"),
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


def build_user_facing_message(
    metadata: JiraCreateMetadata,
    request: CreateJiraAgentRequest,
    merged_values: dict[str, Any],
    missing: list[MissingRequiredField],
    *,
    status: str,
) -> str:
    project = request.project_label or metadata.project_key or "selected project"
    issue_type = request.issue_type_label or metadata.issue_type_name or "selected issue type"
    lines: list[str] = []

    if status == "ready":
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
) -> CreateJiraAgentResponse:
    unresolved = missing_required_for_agent(metadata, merged_values, requirement=requirement)
    combined = unresolved + [item for item in (extra_missing or []) if item.id not in {m.id for m in unresolved}]
    combined += [item for item in response.missing_required_fields if item.id == "__clarification__"]
    status = "ready" if not combined else "needs_information"
    message = build_user_facing_message(metadata, request, merged_values, combined, status=status)
    return CreateJiraAgentResponse(
        status=status,
        message=message,
        fields=response.fields,
        missing_required_fields=combined,
    )


async def analyze_requirement(
    provider: LLMProvider,
    metadata: JiraCreateMetadata,
    request: CreateJiraAgentRequest,
    config: JiraConnectionConfig,
) -> CreateJiraAgentResponse:
    last_user = next((message.content for message in reversed(request.messages) if message.role == "user"), "")
    preprocessed = preprocess_user_message(last_user, metadata)
    preprocessed_block = format_preprocessed_for_llm(preprocessed, metadata)

    merged_provided = dict(preprocessed.provided_fields)
    conversation = "\n".join(f"{message.role.upper()}: {message.content}" for message in request.messages)
    prompt = (
        f"{AGENT_RULES}\n\n"
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

    validated = validate_agent_payload(payload, metadata)
    candidate_fields = {**validated.fields, **merged_provided}
    candidate_fields = apply_summary_description_fallback(candidate_fields, preprocessed.requirement)

    resolved_fields, resolve_missing = await resolve_agent_fields(
        config,
        metadata,
        candidate_fields,
        project_id=request.project_id,
        project_key=metadata.project_key,
    )

    merged = merge_agent_fields(
        metadata,
        request.current_values,
        resolved_fields,
        set(request.user_edited_field_ids),
    )
    enforced = enforce_mandatory_fields(
        metadata,
        request,
        validated,
        merged,
        requirement=preprocessed.requirement,
        extra_missing=resolve_missing,
    )
    enforced.fields = merged
    return enforced
