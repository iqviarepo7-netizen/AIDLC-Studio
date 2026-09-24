from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException

from .connection_models import JiraConnectionConfig
from .jira_create_agent_preprocess import LinkedWorkItemIntent
from .jira_create_models import (
    CreateJiraIssueLinkRequest,
    JiraCreateMetadata,
    JiraIssueLinkTypeOption,
    MissingRequiredField,
    ParsedJiraField,
)
from .jira_create_validation import field_is_empty
from .jira_field_parser import schema_is_gh_sprint
from .jira_user_field import is_automatic_or_empty_user_value, is_probable_jira_account_id

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_DATE_PREFIX_RE = re.compile(r"(?i)^(as|is|should\s+be|on)\s+")
_LINK_SYNTHETIC_ID = "__linked_work_items__"


def _exact_option_match(field: ParsedJiraField, raw: str) -> str | None:
    needle = raw.strip().lower()
    if not needle:
        return None
    for option in field.options:
        if option.label.strip().lower() == needle or str(option.value).strip().lower() == needle:
            return str(option.value)
    return None


def _parsed_field_is_sprint(field: ParsedJiraField) -> bool:
    raw = field.raw_field if isinstance(field.raw_field, dict) else {}
    schema = raw.get("schema") if isinstance(raw.get("schema"), dict) else {}
    return field.type == "select" and schema_is_gh_sprint(schema)


def _option_indicates_active_sprint(label: str) -> bool:
    lowered = label.strip().lower()
    if lowered.startswith("active:"):
        return True
    if "(active)" in lowered:
        return True
    return lowered.endswith(" active")


def _option_indicates_future_sprint(label: str) -> bool:
    lowered = label.strip().lower()
    if lowered.startswith("future:"):
        return True
    if "(future)" in lowered:
        return True
    return lowered.endswith(" future")


def _match_sprint_option(field: ParsedJiraField, raw: str) -> str | None:
    needle = raw.strip().lower()
    if needle in {"active sprint", "active", "current sprint"}:
        active_options = [option for option in field.options if _option_indicates_active_sprint(option.label)]
        if active_options:
            return str(active_options[0].value)
        return None
    if needle in {"future sprint", "future"}:
        future_options = [option for option in field.options if _option_indicates_future_sprint(option.label)]
        if future_options:
            return str(future_options[0].value)
        return None
    exact = _exact_option_match(field, raw)
    if exact:
        return exact
    for option in field.options:
        if needle in option.label.strip().lower():
            return str(option.value)
    return None


def _parse_labels_value(raw: str) -> list[str]:
    cleaned = raw.strip()
    if not cleaned:
        return []
    parts = re.split(r"\s*,\s*|\s+and\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _next_week_date_for_weekday(today: date, weekday: int) -> date:
    days_until_next_monday = 7 - today.weekday()
    next_monday = today + timedelta(days=days_until_next_monday)
    return next_monday + timedelta(days=weekday)


def _resolve_relative_date(raw: str) -> str | None:
    cleaned = _DATE_PREFIX_RE.sub("", raw.strip()).strip()
    lowered = cleaned.lower()
    today = date.today()
    relative = re.search(r"(\d+)\s+days?\s+from\s+today", lowered)
    if relative:
        return (today + timedelta(days=int(relative.group(1)))).isoformat()
    if lowered in {"today"}:
        return today.isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned
    weekday: int | None = None
    for name, index in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lowered):
            weekday = index
            break
    if weekday is None:
        return None
    if re.search(r"next\s+week|\bweek\s+next\b", lowered):
        return _next_week_date_for_weekday(today, weekday).isoformat()
    days_ahead = weekday - today.weekday()
    if re.search(r"\bnext\b", lowered):
        if days_ahead <= 0:
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).isoformat()
    if days_ahead < 0:
        days_ahead += 7
    return (today + timedelta(days=days_ahead)).isoformat()


def _verb_matches(needle: str, verb: str) -> bool:
    n = needle.strip().lower()
    v = verb.strip().lower()
    if not n or not v:
        return False
    if n == v:
        return True
    tokens = re.findall(r"[a-z]+", v)
    for token in tokens:
        if token == n:
            return True
        if min(len(token), len(n)) >= 4 and (token.startswith(n) or n.startswith(token)):
            return True
    return False


def match_link_relationship(
    intent: str,
    link_types: list[JiraIssueLinkTypeOption],
) -> tuple[str, str] | None:
    needle = intent.strip().lower()
    if not needle or not link_types:
        return None
    for role, attr in (("outward", "outward"), ("inward", "inward")):
        for link_type in link_types:
            verb = str(getattr(link_type, attr) or "")
            if _verb_matches(needle, verb):
                return str(link_type.id), role
    for link_type in link_types:
        if _verb_matches(needle, link_type.name):
            if _verb_matches(needle, link_type.outward):
                return str(link_type.id), "outward"
            if _verb_matches(needle, link_type.inward):
                return str(link_type.id), "inward"
            return str(link_type.id), "outward"
    return None


async def _search_issue_key(
    config: JiraConnectionConfig,
    *,
    project_id: str,
    raw: str,
) -> tuple[str | None, str | None, list[str]]:
    from .jira_create_service import canonicalize_jira_issue_key, match_jira_issue_key, search_issues

    query = canonicalize_jira_issue_key(raw) or raw.strip()
    try:
        issues = await search_issues(config, project_id=project_id, query=query)
    except HTTPException:
        return None, None, []
    items = [
        {"label": issue.label, "value": issue.value, "issue_id": issue.issue_id or ""}
        for issue in issues
    ]
    key, labels = match_jira_issue_key(raw, items)
    if not key:
        return None, None, labels
    issue_id = next(
        (str(item.get("issue_id") or "").strip() or None for item in items if str(item.get("value") or "") == key),
        None,
    )
    return key, issue_id, labels


async def _resolve_sprint_value(
    config: JiraConnectionConfig,
    field: ParsedJiraField,
    raw: str,
    *,
    project_id: str,
    project_key: str | None,
) -> tuple[str | None, list[str]]:
    from .jira_create_models import JiraFieldOption
    from .jira_create_service import _coerce_sprint_field_value, fetch_project_board_sprints

    def coerced_match(candidate: ParsedJiraField) -> str | None:
        matched = _match_sprint_option(candidate, raw)
        if not matched:
            return None
        sprint_id = _coerce_sprint_field_value(candidate, matched)
        if sprint_id is None:
            return None
        return str(sprint_id)

    sprint_id = coerced_match(field)
    if sprint_id:
        return sprint_id, []

    try:
        remote_sprints = await fetch_project_board_sprints(
            config,
            project_key=project_key,
            project_id=project_id,
        )
    except HTTPException:
        remote_sprints = []
    if remote_sprints:
        enriched = field.model_copy(deep=True)
        enriched.options = [
            JiraFieldOption(label=item["label"], value=item["value"]) for item in remote_sprints
        ]
        sprint_id = coerced_match(enriched)
        if sprint_id:
            return sprint_id, [option.label for option in enriched.options[:8]]

    return None, [option.label for option in field.options[:8]]


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
        if exact and is_probable_jira_account_id(exact):
            return exact, []
        from .jira_create_service import resolve_assignable_user_value

        return await resolve_assignable_user_value(
            config,
            project_key=project_key,
            project_id=project_id,
            raw=raw,
        )

    if field.type == "parent":
        from .jira_create_service import (
            match_jira_issue_key,
            parent_field_expects_issue_id,
            parent_form_value,
            search_parent_issues,
        )

        eligible = await search_parent_issues(
            config,
            project_id=project_id,
            project_key=project_key,
            issue_type_id=metadata.issue_type_id,
            field=field,
            query=raw,
        )
        option_items = [{"label": option.label, "value": option.value} for option in eligible]
        labels = [option.label for option in eligible[:8]]
        issue_key, _match_labels = match_jira_issue_key(raw, option_items)
        if not issue_key:
            return None, labels or _match_labels
        issue_id = None
        for option in field.options:
            if str(option.value).strip() == issue_key and str(option.value).strip().isdigit():
                issue_id = str(option.value).strip()
                break
        if issue_id is None and parent_field_expects_issue_id(field.id):
            from .jira_create_service import fetch_issue_id_for_key

            issue_id = await fetch_issue_id_for_key(config, issue_key)
        return parent_form_value(field.id, issue_key=issue_key, issue_id=issue_id), labels

    if field.type in {"select", "radio", "status", "priority", "color-picker"}:
        if _parsed_field_is_sprint(field):
            return await _resolve_sprint_value(
                config,
                field,
                raw,
                project_id=project_id,
                project_key=project_key,
            )
        exact = _exact_option_match(field, raw)
        if exact:
            return exact, []
        return None, [option.label for option in field.options[:8]]

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
        if field.type == "labels" and not field_is_empty(value):
            if isinstance(value, list):
                resolved[field_id] = [str(item).strip() for item in value if str(item).strip()]
            else:
                resolved[field_id] = _parse_labels_value(str(value))
            continue
        if field.type in {"date", "datetime"} and not field_is_empty(value):
            resolved_date = _resolve_relative_date(str(value))
            if resolved_date:
                resolved[field_id] = resolved_date
            else:
                clarifications.append(
                    MissingRequiredField(
                        id=field_id,
                        label=field.label,
                        question=(
                            f"I couldn't convert '{value}' into a {field.label}. "
                            f"Please provide a date such as YYYY-MM-DD or a relative expression."
                        ),
                    )
                )
                resolved.pop(field_id, None)
            continue
        if field.type not in {"user", "parent", "select", "radio", "status", "priority", "color-picker"}:
            continue
        if field_is_empty(value):
            continue
        if field.type == "user":
            if (
                str(value).strip() in {str(option.value) for option in field.options}
                and is_probable_jira_account_id(value)
            ):
                continue
        elif str(value).strip() in {str(option.value) for option in field.options}:
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
                    f"I couldn't find a {field.label} matching '{value}'. "
                    f"Please provide a valid {field.label}."
                    + (f" Relevant Jira options: {hint}." if options else "")
                ),
            )
        )
        resolved.pop(field_id, None)

    from .jira_create_service import normalize_parent_form_values, normalize_sprint_form_values_with_board

    resolved = await normalize_parent_form_values(config, metadata, resolved)
    resolved = await normalize_sprint_form_values_with_board(
        config,
        metadata,
        resolved,
        project_key=project_key,
        project_id=project_id,
    )
    return resolved, clarifications


def _linked_clarification(question: str) -> MissingRequiredField:
    return MissingRequiredField(id=_LINK_SYNTHETIC_ID, label="Linked work items", question=question)


async def resolve_linked_work_items(
    config: JiraConnectionConfig,
    intents: list[LinkedWorkItemIntent],
    *,
    project_id: str,
) -> tuple[list[CreateJiraIssueLinkRequest], list[MissingRequiredField]]:
    if not intents:
        return [], []

    from .jira_create_service import list_issue_link_types

    try:
        link_types = await list_issue_link_types(config)
    except HTTPException:
        link_types = []

    resolved: list[CreateJiraIssueLinkRequest] = []
    clarifications: list[MissingRequiredField] = []
    seen: set[tuple[str, str, str]] = set()

    for intent in intents:
        relationship = intent.relationship_intent.strip()
        target = intent.target_intent.strip()
        if not relationship:
            clarifications.append(_linked_clarification("What link relationship should we use for the linked work item?"))
            continue
        if not target:
            clarifications.append(_linked_clarification("Which Jira issue should this work item be linked to?"))
            continue

        matched = match_link_relationship(relationship, link_types)
        if not matched:
            clarifications.append(
                _linked_clarification(
                    f"I couldn't find a link relationship matching '{relationship}'. "
                    "Please name the Linked work items relationship."
                )
            )
            continue

        target_key, _issue_id, _labels = await _search_issue_key(config, project_id=project_id, raw=target)
        if not target_key:
            clarifications.append(
                _linked_clarification(
                    f"I couldn't find a work item matching '{target}'. Please provide a valid issue key."
                )
            )
            continue

        link_type_id, new_issue_role = matched
        key = (link_type_id, target_key, new_issue_role)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(
            CreateJiraIssueLinkRequest(
                link_type_id=link_type_id,
                target_issue_key=target_key,
                new_issue_role=new_issue_role,  # type: ignore[arg-type]
            )
        )

    return resolved, clarifications
