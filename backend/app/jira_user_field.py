from __future__ import annotations

from typing import Any

from .jira_create_validation import field_is_empty

_AUTOMATIC_USER_TOKENS = frozenset(
    {
        "-1",
        "automatic",
        "unassigned",
        "default",
        "assignee",
        "auto",
    }
)


def is_automatic_or_empty_user_value(value: Any) -> bool:
    if field_is_empty(value):
        return True
    normalized = str(value).strip().lower()
    if normalized in _AUTOMATIC_USER_TOKENS:
        return True
    return normalized.startswith("automatic")


def is_probable_jira_account_id(value: Any) -> bool:
    """Jira accountIds are never free-form display names (no spaces)."""
    if is_automatic_or_empty_user_value(value):
        return True
    text = str(value).strip()
    if not text:
        return False
    return " " not in text
