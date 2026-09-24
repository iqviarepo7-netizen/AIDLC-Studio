from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .connection_models import JiraConnectionConfig
from .jira_create_models import JiraCreateMetadata, MissingRequiredField, ParsedJiraField
from .jira_create_validation import field_is_empty
from .jira_user_field import is_automatic_or_empty_user_value


def _exact_option_match(field: ParsedJiraField, raw: str) -> str | None:
    needle = raw.strip().lower()
    if not needle:
        return None
    for option in field.options:
        if option.label.strip().lower() == needle or str(option.value).strip().lower() == needle:
            return str(option.value)
    return None


def _fuzzy_option_match(field: ParsedJiraField, raw: str) -> str | None:
    needle = raw.strip().lower()
    if not needle:
        return None
    for option in field.options:
        label = option.label.strip().lower()
        if needle in label or label in needle:
            return str(option.value)
    return None


def _pick_from_search_results(
    raw: str,
    items: list[dict[str, str]],
) -> tuple[str | None, list[str]]:
    needle = raw.strip().lower()
    labels = [item["label"] for item in items]
    for item in items:
        if item["label"].strip().lower() == needle:
            return item["value"], labels
        if item["value"].strip().lower() == needle:
            return item["value"], labels
    if items:
        return items[0]["value"], labels
    return None, labels


async def resolve_field_value(
    config: JiraConnectionConfig,
    metadata: JiraCreateMetadata,
    field: ParsedJiraField,
    raw_value: Any,
    *,
    project_id: str,
    project_key: str | None,
) -> tuple[Any | None, list[str]]:
    if field_is_empty(raw_value):
        return None, []
    raw = str(raw_value).strip()
    if field.type == "user":
        if is_automatic_or_empty_user_value(raw):
            return raw, []
        exact = _exact_option_match(field, raw)
        if exact:
            return exact, []
        from .jira_create_service import search_assignable_users

        try:
            users = await search_assignable_users(
                config,
                project_key=project_key,
                project_id=project_id,
                query=raw,
            )
        except HTTPException:
            users = []
        value, labels = _pick_from_search_results(raw, users)
        return value, labels

    if field.type == "parent" and field.searchable:
        exact = _exact_option_match(field, raw)
        if exact:
            return exact, []
        from .jira_create_service import search_issues

        issues = await search_issues(config, project_id=project_id, query=raw)
        items = [{"label": issue.label, "value": issue.value} for issue in issues]
        value, labels = _pick_from_search_results(raw, items)
        return value, labels

    if field.type in {"select", "radio", "status", "priority", "color-picker"}:
        exact = _exact_option_match(field, raw)
        if exact:
            return exact, []
        fuzzy = _fuzzy_option_match(field, raw)
        if fuzzy:
            return fuzzy, []
        return None, [option.label for option in field.options[:8]]

    if field.type == "parent":
        exact = _exact_option_match(field, raw)
        return exact or raw, []

    return raw, []


async def resolve_agent_fields(
    config: JiraConnectionConfig,
    metadata: JiraCreateMetadata,
    fields: dict[str, Any],
    *,
    project_id: str,
    project_key: str | None,
) -> tuple[dict[str, Any], list[MissingRequiredField]]:
    resolved: dict[str, Any] = dict(fields)
    clarifications: list[MissingRequiredField] = []

    for field_id, value in list(fields.items()):
        field = metadata.fields.get(field_id)
        if not field:
            continue
        if field.type not in {"user", "parent", "select", "radio", "status", "priority", "color-picker"}:
            continue
        if field_is_empty(value):
            continue
        if str(value).strip() in {str(option.value) for option in field.options}:
            continue

        resolved_value, options = await resolve_field_value(
            config,
            metadata,
            field,
            value,
            project_id=project_id,
            project_key=project_key,
        )
        if resolved_value is not None and not field_is_empty(resolved_value):
            resolved[field_id] = resolved_value
            continue

        hint = ", ".join(options[:6]) if options else "no Jira matches"
        clarifications.append(
            MissingRequiredField(
                id=field_id,
                label=field.label,
                question=(
                    f"I couldn't match '{value}' for {field.label}. "
                    f"Please provide a valid value. Relevant Jira options: {hint}."
                ),
            )
        )
        resolved.pop(field_id, None)

    return resolved, clarifications
