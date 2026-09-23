from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException

from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS
from .jira_create_models import CreateJiraAgentRequest, CreateJiraAgentResponse, JiraCreateMetadata, MissingRequiredField
from .jira_create_validation import extract_json_object, field_is_empty, merge_agent_fields, missing_required_fields
from .llm import LLMProvider

logger = logging.getLogger(__name__)

AGENT_RULES = """
You are the Create Jira Agent for AIDLC Studio.
Transform natural-language requirements into Jira field values using ONLY the provided schema.

Rules:
1. Never invent factual business details (client, environment, severity, priority, assignee, root cause, versions).
2. Draft Summary and Description from the requirement when safe.
3. For select/radio/checkbox fields, values MUST match one of the allowed option values exactly.
4. Do not create Jira issues; only propose field values for human review.
5. Output JSON only with this shape:
{
  "status": "needs_information" | "ready",
  "message": "optional short note",
  "fields": { "<field-id>": <value> },
  "missingRequiredFields": [{ "id": "...", "label": "...", "question": "..." }]
}
6. Use field ids exactly as provided in the schema.
7. Project and Issue Type are already selected in the UI — never ask for them.
8. Do not use vague phrases like "I need more details" without naming missing fields.
"""


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
        }
        if field.options:
            entry["options"] = [{"label": option.label, "value": option.value} for option in field.options]
        if field.description:
            entry["description"] = field.description
        fields.append(entry)
    return json.dumps({"project_id": metadata.project_id, "issue_type_id": metadata.issue_type_id, "fields": fields}, indent=2)


def validate_agent_payload(payload: dict[str, Any], metadata: JiraCreateMetadata) -> CreateJiraAgentResponse:
    status = payload.get("status")
    if status not in {"needs_information", "ready"}:
        status = "needs_information"
    message = str(payload.get("message") or "")
    raw_fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    known = set(metadata.fields.keys())
    fields: dict[str, Any] = {}
    for field_id, value in raw_fields.items():
        field_key = str(field_id)
        if field_key not in known or field_key in CONTEXT_MANAGED_FIELD_IDS:
            continue
        field = metadata.fields[field_key]
        if field.type in {"select", "radio"} and field.options:
            allowed = {option.value for option in field.options}
            if str(value) not in allowed:
                continue
        if field.type == "checkbox" and field.options:
            allowed = {option.value for option in field.options}
            if isinstance(value, list):
                fields[field_key] = [str(item) for item in value if str(item) in allowed]
            elif str(value) in allowed:
                fields[field_key] = [str(value)]
            continue
        fields[field_key] = value

    missing_raw = payload.get("missingRequiredFields") or payload.get("missing_required_fields") or []
    missing: list[MissingRequiredField] = []
    if isinstance(missing_raw, list):
        for item in missing_raw:
            if not isinstance(item, dict):
                continue
            field_id = str(item.get("id") or "")
            if field_id not in known or field_id in CONTEXT_MANAGED_FIELD_IDS:
                continue
            missing.append(
                MissingRequiredField(
                    id=field_id,
                    label=str(item.get("label") or metadata.fields[field_id].label),
                    question=str(item.get("question") or f"Please provide {metadata.fields[field_id].label}."),
                )
            )

    return CreateJiraAgentResponse(status=status, message=message, fields=fields, missing_required_fields=missing)


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

    if missing:
        if len(missing) == 1:
            item = missing[0]
            lines.append("I still need one Jira-required field before you can create the issue:")
            lines.append("")
            lines.append(f"• {item.label} *")
            lines.append(f"  {item.question}")
        else:
            lines.append(f"I still need {len(missing)} Jira-required fields before you can create the issue:")
            lines.append("")
            for index, item in enumerate(missing, start=1):
                lines.append(f"{index}. {item.label} *")
                lines.append(f"   {item.question}")
        lines.append("")
        lines.append("Reply with those details and I'll fill the Jira form automatically.")
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


def enforce_mandatory_fields(
    metadata: JiraCreateMetadata,
    request: CreateJiraAgentRequest,
    response: CreateJiraAgentResponse,
    merged_values: dict[str, Any],
) -> CreateJiraAgentResponse:
    unresolved = missing_required_fields(metadata, merged_values)
    status = "ready" if not unresolved else "needs_information"
    message = build_user_facing_message(metadata, request, merged_values, unresolved, status=status)
    return CreateJiraAgentResponse(
        status=status,
        message=message,
        fields=response.fields,
        missing_required_fields=unresolved,
    )


async def analyze_requirement(
    provider: LLMProvider,
    metadata: JiraCreateMetadata,
    request: CreateJiraAgentRequest,
) -> CreateJiraAgentResponse:
    conversation = "\n".join(f"{message.role.upper()}: {message.content}" for message in request.messages)
    prompt = (
        f"{AGENT_RULES}\n\n"
        f"JIRA FIELD SCHEMA:\n{build_schema_prompt(metadata)}\n\n"
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
    merged = merge_agent_fields(metadata, request.current_values, validated.fields, set(request.user_edited_field_ids))
    enforced = enforce_mandatory_fields(metadata, request, validated, merged)
    enforced.fields = merged
    return enforced
