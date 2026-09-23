from __future__ import annotations

import json
import re
from typing import Any

from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS
from .jira_create_models import JiraCreateMetadata, MissingRequiredField


def field_question(field_id: str, label: str) -> str:
    normalized = label.strip().lower()
    if field_id == "reporter" or normalized == "reporter":
        return "Who should be the Jira reporter for this issue?"
    if "client" in normalized:
        return "Which client is this issue for?"
    if "environment" in normalized:
        return "Which environment does this apply to (for example Dev, QA, Production)?"
    if field_id == "assignee" or normalized == "assignee":
        return "Who should this issue be assigned to?"
    if normalized == "priority":
        return "Which priority should this issue use?"
    return f"What value should we use for {label}?"


def field_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def missing_required_fields(metadata: JiraCreateMetadata, values: dict[str, Any]) -> list[MissingRequiredField]:
    missing: list[MissingRequiredField] = []
    for field_id, field in metadata.fields.items():
        if field_id in CONTEXT_MANAGED_FIELD_IDS:
            continue
        if not field.required:
            continue
        if field_is_empty(values.get(field_id)):
            missing.append(
                MissingRequiredField(
                    id=field_id,
                    label=field.label,
                    question=field_question(field_id, field.label),
                )
            )
    return missing


def validate_select_values(metadata: JiraCreateMetadata, values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for field_id, field in metadata.fields.items():
        if field.type not in {"select", "radio"}:
            continue
        value = values.get(field_id)
        if field_is_empty(value):
            continue
        allowed = {option.value for option in field.options}
        if allowed and str(value) not in allowed:
            errors[field_id] = f"{field.label} must be one of the allowed Jira options."
    return errors


def merge_agent_fields(
    metadata: JiraCreateMetadata,
    current: dict[str, Any],
    proposed: dict[str, Any],
    user_edited: set[str],
) -> dict[str, Any]:
    merged = dict(current)
    known_ids = set(metadata.fields.keys())
    for field_id, value in proposed.items():
        if field_id not in known_ids:
            continue
        if field_id in user_edited and not field_is_empty(merged.get(field_id)):
            continue
        if not field_is_empty(value):
            merged[field_id] = value
    return merged


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("Agent response was not a JSON object.")
    return payload
