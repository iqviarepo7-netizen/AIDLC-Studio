from __future__ import annotations

import html
import json
import re
from typing import Any, Literal

from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS, SYNTHETIC_TAB_IDS
from .jira_create_models import JiraFieldOption, JiraTabDefinition, ParsedJiraField

FieldType = Literal["text", "textarea", "select", "checkbox", "radio", "unsupported"]

_OPTION_RE = re.compile(r"<option\b([^>]*)>(.*?)</option>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_BOOL_ATTR_RE = re.compile(r"\b(disabled|selected)\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<(\w+)\b([^>]*)>", re.IGNORECASE)


def _decode_text(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", value)
    return html.unescape(cleaned).strip()


def _parse_option_attrs(attr_text: str) -> dict[str, str]:
    attrs = {match.group(1).lower(): match.group(2) for match in _ATTR_RE.finditer(attr_text)}
    for match in _BOOL_ATTR_RE.finditer(attr_text):
        attrs[match.group(1).lower()] = "true"
    return attrs


def parse_select_options(edit_html: str) -> list[JiraFieldOption]:
    options: list[JiraFieldOption] = []
    for match in _OPTION_RE.finditer(edit_html or ""):
        attrs = _parse_option_attrs(match.group(1))
        label = _decode_text(match.group(2))
        value = attrs.get("value", label)
        if not label and not value:
            continue
        options.append(
            JiraFieldOption(
                label=label or value,
                value=value,
                disabled="disabled" in attrs,
                selected="selected" in attrs,
            )
        )
    return options


def detect_field_type(edit_html: str) -> FieldType:
    snippet = (edit_html or "").lower()
    if "<select" in snippet:
        return "select"
    if "<textarea" in snippet:
        return "textarea"
    if 'type="checkbox"' in snippet or "type='checkbox'" in snippet:
        return "checkbox"
    if 'type="radio"' in snippet or "type='radio'" in snippet:
        return "radio"
    if "<input" in snippet and ('type="text"' in snippet or "type='text'" in snippet or "type=" not in snippet):
        return "text"
    if "<input" in snippet:
        return "text"
    return "unsupported"


def extract_field_reference(item: Any) -> tuple[str, str | None]:
    if isinstance(item, dict):
        field_id = str(item.get("id") or item.get("fieldId") or item.get("key") or "")
        label = item.get("label") or item.get("name")
        return field_id, str(label) if label else None
    if isinstance(item, str):
        stripped = item.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                field_id = str(payload.get("id") or payload.get("fieldId") or payload.get("key") or "")
                label = payload.get("label") or payload.get("name")
                if field_id:
                    return field_id, str(label) if label else None
        return stripped, None
    if item is None:
        return "", None
    return str(item), None


def options_from_allowed_values(field: dict[str, Any]) -> list[JiraFieldOption]:
    allowed = field.get("allowedValues")
    if not isinstance(allowed, list):
        return []
    options: list[JiraFieldOption] = []
    for item in allowed:
        if not isinstance(item, dict):
            continue
        value = str(item.get("id") or item.get("value") or item.get("name") or "")
        label = str(item.get("name") or item.get("value") or item.get("displayName") or value)
        if value or label:
            options.append(JiraFieldOption(label=label or value, value=value or label))
    return options


def extract_default_value(field: dict[str, Any]) -> Any | None:
    if field.get("hasDefaultValue") and "defaultValue" in field:
        default = field.get("defaultValue")
        if isinstance(default, dict):
            return str(default.get("id") or default.get("name") or default.get("value") or "")
        if default is not None:
            return default
    for option in options_from_allowed_values(field):
        if option.selected:
            return option.value
    return None


def extract_description(field: dict[str, Any]) -> str | None:
    for key in ("description", "helpText", "tooltip"):
        raw = field.get(key)
        if isinstance(raw, str) and raw.strip():
            return _decode_text(raw)
    return None


def infer_type_from_schema(schema: dict[str, Any], field_id: str) -> FieldType:
    schema_type = schema.get("type")
    custom = str(schema.get("custom") or "")
    system = str(schema.get("system") or "")
    if field_id == "description" or system == "description" or "textarea" in custom.lower():
        return "textarea"
    if schema_type in {"option", "priority", "issuetype", "project", "user"}:
        return "select"
    if schema_type == "array":
        return "checkbox"
    if schema_type in {"string", "number"}:
        return "text"
    if schema_type == "date" or schema_type == "datetime":
        return "text"
    return "unsupported"


def parse_jira_field(field_id: str, field: dict[str, Any], *, tab: str | None = None, label_hint: str | None = None) -> ParsedJiraField:
    if isinstance(field, dict) and not field.get("editHtml") and field.get("id"):
        nested_id, nested_label = extract_field_reference(field)
        if nested_id:
            field_id = nested_id
            label_hint = label_hint or nested_label

    edit_html = str(field.get("editHtml") or field.get("edit_html") or "")
    field_type = detect_field_type(edit_html)
    schema = field.get("schema") if isinstance(field.get("schema"), dict) else {}
    if field_type == "unsupported":
        field_type = infer_type_from_schema(schema, field_id)

    options = parse_select_options(edit_html) if field_type in {"select", "checkbox", "radio"} else []
    if field_type in {"select", "checkbox", "radio"} and not options:
        options = options_from_allowed_values(field)
    if field_type in {"checkbox", "radio"} and not options:
        options = parse_select_options(edit_html)
    if field_type == "select" and not options and schema.get("type") in {"user", "option", "priority"}:
        field_type = "text"

    label = str(field.get("label") or field.get("name") or label_hint or field_id)
    required = bool(field.get("required"))
    return ParsedJiraField(
        id=field_id,
        label=label,
        required=required,
        type=field_type,
        options=options,
        description=extract_description(field),
        tab=tab,
        default_value=extract_default_value(field),
        raw_field=field,
    )


def sort_tabs(raw_tabs: list[dict[str, Any]]) -> list[JiraTabDefinition]:
    tabs: list[JiraTabDefinition] = []
    for index, tab in enumerate(raw_tabs):
        if not isinstance(tab, dict):
            continue
        tab_id = str(tab.get("id") or tab.get("name") or f"tab-{index}")
        label = str(tab.get("label") or tab.get("name") or tab_id)
        position_raw = tab.get("position", index)
        try:
            position = int(position_raw)
        except (TypeError, ValueError):
            position = index
        field_ids = tab.get("fields") or []
        fields: list[str] = []
        if isinstance(field_ids, list):
            for item in field_ids:
                field_id, _label = extract_field_reference(item)
                if field_id:
                    fields.append(field_id)
        tabs.append(JiraTabDefinition(id=tab_id, label=label, position=position, fields=fields))
    tabs.sort(key=lambda item: item.position)
    return tabs


def normalize_jira_metadata(
    raw: dict[str, Any],
    *,
    project_id: str,
    issue_type_id: str,
    project_key: str | None = None,
    issue_type_name: str | None = None,
) -> tuple[dict[str, ParsedJiraField], list[JiraTabDefinition]]:
    raw_fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    parsed_fields: dict[str, ParsedJiraField] = {}
    for raw_key, field in raw_fields.items():
        if not isinstance(field, dict):
            continue
        field_id, label_hint = extract_field_reference(raw_key)
        if not field_id and field.get("id"):
            field_id = str(field.get("id"))
        if not field_id:
            field_id, label_hint = extract_field_reference(field)
        if not field_id:
            continue
        parsed_fields[field_id] = parse_jira_field(field_id, field, label_hint=label_hint)

    raw_tabs = raw.get("sortedTabs") or raw.get("sorted_tabs") or []
    tabs = sort_tabs(raw_tabs if isinstance(raw_tabs, list) else [])

    for tab in tabs:
        tab.fields = [field_id for field_id in tab.fields if field_id not in CONTEXT_MANAGED_FIELD_IDS]
        for field_id in tab.fields:
            if field_id in parsed_fields:
                parsed_fields[field_id].tab = tab.id

    tabs = [
        JiraTabDefinition(id=tab.id, label=tab.label, position=tab.position, fields=[fid for fid in tab.fields if fid in parsed_fields])
        for tab in tabs
    ]
    tabs = [tab for tab in tabs if tab.fields and tab.id.lower() not in SYNTHETIC_TAB_IDS]

    for field_id in list(parsed_fields.keys()):
        if field_id in CONTEXT_MANAGED_FIELD_IDS:
            del parsed_fields[field_id]

    _ = project_id, issue_type_id, project_key, issue_type_name
    return parsed_fields, tabs
