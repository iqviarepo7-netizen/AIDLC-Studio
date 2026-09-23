from __future__ import annotations

# Selected in the modal header — never treat as dynamic form requirements.
CONTEXT_MANAGED_FIELD_IDS = frozenset(
    {
        "project",
        "issuetype",
        "projectField",
        "issuetypeField",
        "parent",
    }
)

# Synthetic tabs created by our integration — never show in UI.
SYNTHETIC_TAB_IDS = frozenset({"general", "details", "default"})
