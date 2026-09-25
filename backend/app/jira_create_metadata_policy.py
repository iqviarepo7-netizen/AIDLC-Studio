from __future__ import annotations

from .jira_create_constants import SYNTHETIC_TAB_IDS
from .jira_create_models import JiraTabDefinition, ParsedJiraField

DESCRIPTION_FIELD_ID = "description"
REPORTER_FIELD_ID = "reporter"


def apply_create_jira_field_policy(
    fields: dict[str, ParsedJiraField],
    tabs: list[JiraTabDefinition],
) -> tuple[dict[str, ParsedJiraField], list[JiraTabDefinition], list[str], list[str]]:
    """
    Application policy on normalized Jira create metadata (order matters):
    1. reporter.required = false
    2. description.required = true
    3. keep all Create-screen fields (required and optional)
    4. sync tab field references and drop empty tabs
    5. flatten sole default Quick Create \"General\" tab (no synthetic tab UI)

    Returns create-form fields, tab layout, and effective required field ids for agent/validation.
    """
    working: dict[str, ParsedJiraField] = {
        field_id: field.model_copy(deep=True) for field_id, field in fields.items()
    }

    if REPORTER_FIELD_ID in working:
        working[REPORTER_FIELD_ID].required = False
    if DESCRIPTION_FIELD_ID in working:
        working[DESCRIPTION_FIELD_ID].required = True

    allowed_ids = set(working.keys())
    required_field_ids = [
        field_id
        for field_id, field in working.items()
        if field.required
    ]

    synced_tabs: list[JiraTabDefinition] = []
    for tab in tabs:
        if tab.id.lower() in SYNTHETIC_TAB_IDS:
            continue
        field_refs = [field_id for field_id in tab.fields if field_id in allowed_ids]
        if field_refs:
            synced_tabs.append(
                JiraTabDefinition(
                    id=tab.id,
                    label=tab.label,
                    position=tab.position,
                    fields=field_refs,
                )
            )

    field_order: list[str] = []
    for tab in sorted(synced_tabs, key=lambda item: item.position):
        for field_id in tab.fields:
            if field_id in allowed_ids and field_id not in field_order:
                field_order.append(field_id)
    for field_id in working:
        if field_id not in field_order:
            field_order.append(field_id)

    synced_tabs = _flatten_solitary_general_tab(synced_tabs)
    return working, synced_tabs, required_field_ids, field_order


def _flatten_solitary_general_tab(tabs: list[JiraTabDefinition]) -> list[JiraTabDefinition]:
    """Jira Quick Create often returns one catch-all \"General\" group — render fields flat instead."""
    if len(tabs) != 1:
        return tabs
    tab = tabs[0]
    if tab.label.strip().lower() == "general":
        return []
    return tabs
