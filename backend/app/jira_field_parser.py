from __future__ import annotations

import html
import json
import re
from typing import Any, Literal

from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS, SYNTHETIC_TAB_IDS
from .jira_create_models import JiraFieldOption, JiraTabDefinition, ParsedJiraField

FieldType = Literal[
    "text",
    "textarea",
    "number",
    "select",
    "checkbox",
    "radio",
    "labels",
    "date",
    "datetime",
    "user",
    "status",
    "priority",
    "parent",
    "color-picker",
    "readonly",
    "unsupported",
]

_COLOR_OPTION_ATTR_RE = re.compile(
    r'data-(?:option-id|color-id|value)\s*=\s*"([^"]+)"[^>]*(?:data-(?:color|background-color|swatch)\s*=\s*"([^"]*)")?',
    re.IGNORECASE,
)
_STYLE_BG_RE = re.compile(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8}|rgb[a]?\([^)]+\))", re.IGNORECASE)

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


def schema_is_gh_sprint(schema: dict[str, Any]) -> bool:
    custom = str(schema.get("custom") or "").lower()
    system = str(schema.get("system") or "").lower()
    return "gh-sprint" in custom or system == "sprint"


def parse_select_options(edit_html: str, *, skip_empty_values: bool = False) -> list[JiraFieldOption]:
    options: list[JiraFieldOption] = []
    for match in _OPTION_RE.finditer(edit_html or ""):
        attrs = _parse_option_attrs(match.group(1))
        label = _decode_text(match.group(2))
        value = attrs.get("value", label)
        if skip_empty_values and not str(value).strip():
            continue
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
    if _schema_suggests_color_picker({}, edit_html):
        return "color-picker"
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


def _swatch_from_allowed_item(item: dict[str, Any]) -> str | None:
    for key in ("color", "backgroundColor", "background", "swatchColor", "hex", "colour"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def allowed_values_suggest_color_picker(field: dict[str, Any]) -> bool:
    allowed = field.get("allowedValues")
    if not isinstance(allowed, list):
        return False
    for item in allowed:
        if isinstance(item, dict) and _swatch_from_allowed_item(item):
            return True
    return False


def _schema_suggests_color_picker(schema: dict[str, Any], edit_html: str) -> bool:
    custom = str(schema.get("custom") or "").lower()
    if any(token in custom for token in ("issue-color", "issuecolor", "epic-color", "color-picker", "swatch", "colour")):
        return True
    snippet = (edit_html or "").lower()
    return any(
        token in snippet
        for token in ("issue-color", "color-picker", "colour-picker", "colorpicker", "data-color", "color-swatch")
    )


def parse_color_options_from_edit_html(edit_html: str) -> list[JiraFieldOption]:
    options: list[JiraFieldOption] = []
    seen: set[str] = set()
    for match in _COLOR_OPTION_ATTR_RE.finditer(edit_html or ""):
        value = match.group(1)
        swatch = match.group(2) or None
        if value and value not in seen:
            seen.add(value)
            options.append(JiraFieldOption(label=value, value=value, swatch_color=swatch))
    for match in _OPTION_RE.finditer(edit_html or ""):
        attrs = _parse_option_attrs(match.group(1))
        label = _decode_text(match.group(2))
        value = attrs.get("value", label)
        swatch = attrs.get("data-color") or attrs.get("color") or attrs.get("data-background-color")
        if (value or label) and value not in seen:
            seen.add(value)
            options.append(JiraFieldOption(label=label or value, value=value or label, swatch_color=swatch))
    return options


def options_from_allowed_values(field: dict[str, Any]) -> list[JiraFieldOption]:
    allowed = field.get("allowedValues")
    if not isinstance(allowed, list):
        return []
    schema = field.get("schema") if isinstance(field.get("schema"), dict) else {}
    sprint_field = schema_is_gh_sprint(schema)
    options: list[JiraFieldOption] = []
    for item in allowed:
        if not isinstance(item, dict):
            continue
        value = str(
            item.get("accountId")
            or item.get("id")
            or item.get("value")
            or item.get("key")
            or item.get("name")
            or ""
        )
        label = str(
            item.get("displayName")
            or item.get("name")
            or item.get("value")
            or item.get("key")
            or value
        )
        if sprint_field:
            state = item.get("state")
            if isinstance(state, str) and state.strip():
                state_label = state.strip().capitalize()
                if state_label.lower() not in label.lower():
                    label = f"{state_label}: {label}"
        swatch = _swatch_from_allowed_item(item)
        if value or label:
            options.append(
                JiraFieldOption(label=label or value, value=value or label, swatch_color=swatch)
            )
    return options


def options_from_parent_allowed_values(field: dict[str, Any]) -> list[JiraFieldOption]:
    """Parent create metadata: prefer issue keys so UI/agent match Jira hierarchy eligibility."""
    allowed = field.get("allowedValues")
    if not isinstance(allowed, list):
        return []
    options: list[JiraFieldOption] = []
    for item in allowed:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        issue_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or item.get("summary") or item.get("displayName") or "").strip()
        if key:
            value = key
            label = f"{key} — {name}" if name and name.lower() != key.lower() else key
        elif issue_id:
            value = issue_id
            label = name or issue_id
        else:
            continue
        options.append(JiraFieldOption(label=label, value=value))
    return options


def _edit_html_suggests_user_picker(edit_html: str) -> bool:
    snippet = (edit_html or "").lower()
    return any(token in snippet for token in ("userpicker", "user-picker", "assignee", "reporter", "data-user"))


def infer_type_from_schema(
    schema: dict[str, Any],
    field_id: str,
    *,
    edit_html: str = "",
    field: dict[str, Any] | None = None,
) -> FieldType:
    schema_type = schema.get("type")
    custom = str(schema.get("custom") or "")
    custom_lower = custom.lower()
    system = str(schema.get("system") or "")
    if _schema_suggests_color_picker(schema, edit_html) or (field and allowed_values_suggest_color_picker(field)):
        return "color-picker"
    if field_id == "status" or system == "status":
        return "status"
    if field_id == "priority" or system == "priority":
        return "priority"
    if field_id == "parent" or system in {"parent", "parentIssue"}:
        return "parent"
    if field_id == "description" or system == "description" or "textarea" in custom_lower:
        return "textarea"
    if field_id == "labels" or system == "labels":
        return "labels"
    if "gh-sprint" in custom_lower or system == "sprint":
        return "select"
    if schema_type == "user" or system in {"assignee", "reporter"} or field_id in {"assignee", "reporter"}:
        return "user"
    if schema_type in {"option", "issuetype", "project"}:
        return "select"
    if schema_type == "array":
        items = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        if items.get("type") == "string" and (field_id == "labels" or system == "labels"):
            return "labels"
        if items.get("type") in {"option", "user"}:
            return "checkbox"
        return "checkbox"
    if schema_type == "number":
        return "number"
    if schema_type == "string":
        if _edit_html_suggests_user_picker(edit_html):
            return "user"
        return "text"
    if schema_type == "date":
        return "date"
    if schema_type == "datetime":
        return "datetime"
    if schema_type == "issuelink" or "issue" in custom_lower and "parent" in field_id.lower():
        return "parent"
    return "unsupported"


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


def status_submittable_on_create(field: dict[str, Any]) -> bool:
    """Status is workflow-derived on most Jira instances; only submit when metadata marks it editable."""
    if field.get("editable") is not True:
        return False
    allowed = field.get("allowedValues")
    return isinstance(allowed, list) and len(allowed) > 0


def extract_description(field: dict[str, Any]) -> str | None:
    for key in ("description", "helpText", "tooltip"):
        raw = field.get(key)
        if isinstance(raw, str) and raw.strip():
            return _decode_text(raw)
    return None


def parse_jira_field(field_id: str, field: dict[str, Any], *, tab: str | None = None, label_hint: str | None = None) -> ParsedJiraField:
    if isinstance(field, dict) and not field.get("editHtml") and field.get("id"):
        nested_id, nested_label = extract_field_reference(field)
        if nested_id:
            field_id = nested_id
            label_hint = label_hint or nested_label

    edit_html = str(field.get("editHtml") or field.get("edit_html") or "")
    schema = field.get("schema") if isinstance(field.get("schema"), dict) else {}
    schema_type = infer_type_from_schema(schema, field_id, edit_html=edit_html, field=field)
    if field_id == "attachment" or str(schema.get("system") or "") == "attachment":
        field_type: FieldType = "unsupported"
    elif schema_type != "unsupported":
        field_type = schema_type
    elif field.get("editable") is False and not edit_html.strip():
        field_type = "readonly"
    else:
        field_type = detect_field_type(edit_html)
        if field_type == "unsupported":
            field_type = schema_type

    select_like = {"select", "checkbox", "radio", "status", "priority", "parent", "user", "color-picker"}
    options: list[JiraFieldOption] = []
    if field_type == "color-picker":
        options = options_from_allowed_values(field)
        if not options:
            options = parse_color_options_from_edit_html(edit_html)
        if not options:
            options = parse_select_options(edit_html)
    elif field_type in select_like:
        schema_dict = field.get("schema") if isinstance(field.get("schema"), dict) else {}
        if schema_is_gh_sprint(schema_dict):
            options = options_from_allowed_values(field)
            if not options:
                options = parse_select_options(edit_html, skip_empty_values=True)
        elif field_type == "parent":
            options = options_from_parent_allowed_values(field)
            if not options:
                options = options_from_allowed_values(field)
            if not options:
                options = parse_select_options(edit_html, skip_empty_values=True)
        else:
            options = parse_select_options(edit_html)
            if not options:
                options = options_from_allowed_values(field)
        if field_type in {"checkbox", "radio"} and not options:
            options = parse_select_options(edit_html)

    searchable = field_type == "user" and (not options or _edit_html_suggests_user_picker(edit_html))
    multiple = schema.get("type") == "array" and field_type in {"checkbox", "labels"}

    label = str(field.get("label") or field.get("name") or label_hint or field_id)
    required = bool(field.get("required"))
    default_value = extract_default_value(field)
    if field_type == "user" and default_value is None and options:
        for option in options:
            if option.selected:
                default_value = option.value
                break
    if field_type == "user" and default_value is None and field_id == "assignee":
        automatic = next((opt for opt in options if opt.label.strip().lower() == "automatic"), None)
        if automatic:
            default_value = automatic.value

    if field_type == "status" and not status_submittable_on_create(field):
        field_type = "readonly"
        if default_value is None and options:
            selected = next((opt for opt in options if opt.selected), None)
            if selected:
                default_value = selected.label
            elif options:
                default_value = options[0].label

    searchable = searchable or field_type == "parent"

    return ParsedJiraField(
        id=field_id,
        label=label,
        required=required,
        type=field_type,
        options=options,
        searchable=searchable,
        multiple=multiple,
        description=extract_description(field),
        tab=tab,
        default_value=default_value,
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
        if field_id.lower() == "attachment":
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

    field_order = _field_order_from_tabs(tabs, parsed_fields)
    if not field_order:
        field_order = list(parsed_fields.keys())

    _ = project_id, issue_type_id, project_key, issue_type_name
    return parsed_fields, tabs, field_order


def _field_order_from_tabs(tabs: list[JiraTabDefinition], parsed_fields: dict[str, ParsedJiraField]) -> list[str]:
    order: list[str] = []
    for tab in tabs:
        for field_id in tab.fields:
            if field_id in parsed_fields and field_id not in order:
                order.append(field_id)
    return order


def field_order_from_raw(raw: dict[str, Any], parsed_fields: dict[str, ParsedJiraField]) -> list[str]:
    """Preserve Quick Create / screen tab ordering when available."""
    raw_tabs = raw.get("sortedTabs") or raw.get("sorted_tabs") or []
    if isinstance(raw_tabs, list) and raw_tabs:
        order: list[str] = []
        indexed = sorted(
            [tab for tab in raw_tabs if isinstance(tab, dict)],
            key=lambda tab: int(tab.get("position", 0)) if str(tab.get("position", "")).isdigit() else 0,
        )
        for tab in indexed:
            field_ids = tab.get("fields") or []
            if not isinstance(field_ids, list):
                continue
            for item in field_ids:
                field_id, _ = extract_field_reference(item)
                if field_id in parsed_fields and field_id not in order:
                    order.append(field_id)
        if order:
            return order
    return list(parsed_fields.keys())
