from __future__ import annotations

import re
from typing import Any, Literal

from .jira_create_agent_resolve import _exact_option_match
from .jira_create_models import CreateJiraAgentRequest, JiraCreateMetadata, MissingRequiredField, PendingAgentField
from .jira_create_validation import field_is_empty

AgentConversationPhase = Literal["initial_requirement", "field_resolution", "ready_to_create"]

_REQUIREMENT_UPDATE_PATTERNS = (
    re.compile(r"(?i)\b(update|revise|modify)\s+(the\s+)?requirement\b"),
    re.compile(r"(?i)\bchange\s+the\s+requirement\b"),
    re.compile(r"(?i)\bchange\b.{0,48}\brequirement\b"),
    re.compile(r"(?i)\brequirement\b.{0,24}\bchange\b"),
    re.compile(r"(?i)\balso\s+(add|include|make|ensure)\b"),
    re.compile(r"(?i)\b(additionally|in addition)\b"),
)

_FIELD_CHANGE_PATTERNS = (
    re.compile(r"(?i)^change\s+(?P<label>.+?)\s+to\s+(?P<value>.+)$"),
    re.compile(r"(?i)^change\s+(?P<label>.+?)\s+should\s+be\s+(?P<value>.+)$"),
    re.compile(r"(?i)^(?:update|set)\s+(?P<label>.+?)\s+to\s+(?P<value>.+)$"),
    re.compile(r"(?i)^make\s+(?P<label>.+?)\s+(?P<value>.+)$"),
)

_FIELD_MUTATION_HINT = re.compile(r"(?i)\b(change|update|set|make|correct)\b")


def infer_conversation_phase(request: CreateJiraAgentRequest) -> AgentConversationPhase:
    if has_requirement_baseline(request.current_values):
        user_turns = sum(1 for message in request.messages if message.role == "user")
        if user_turns > 1 or request.pending_fields or request.pending_clarification_field_id:
            return "field_resolution"
        if request.conversation_phase in {"field_resolution", "ready_to_create"}:
            return "field_resolution"
    if request.conversation_phase:
        return request.conversation_phase
    return "initial_requirement"


def has_requirement_baseline(values: dict[str, Any]) -> bool:
    return not field_is_empty(values.get("summary")) and not field_is_empty(values.get("description"))


def is_requirement_modification(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if any(pattern.search(text) for pattern in _REQUIREMENT_UPDATE_PATTERNS):
        return True
    if any(pattern.match(text) for pattern in _FIELD_CHANGE_PATTERNS):
        return False
    return False


def initial_user_requirement(messages: list) -> str:
    for message in messages:
        if getattr(message, "role", None) == "user":
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def build_requirement_update_context(request: CreateJiraAgentRequest, change_message: str) -> str:
    initial = initial_user_requirement(request.messages)
    summary = request.current_values.get("summary")
    description = request.current_values.get("description")
    summary_text = str(summary).strip() if summary is not None else ""
    description_text = str(description).strip() if description is not None else ""
    change_text = change_message.strip()
    return (
        "REQUIREMENT UPDATE CONTEXT:\n"
        "Modify the existing functional requirement using the user's change. "
        "Do not treat the change message as a brand-new standalone requirement.\n"
        f"Current functional requirement (original user requirement): {initial or '(none)'}\n"
        f"Current Summary: {summary_text or '(none)'}\n"
        f"Current Description:\n{description_text or '(none)'}\n"
        f"User's requested requirement change: {change_text or '(none)'}\n"
    )


def should_use_field_patch_path(request: CreateJiraAgentRequest, message: str) -> bool:
    if not has_requirement_baseline(request.current_values):
        return False
    if is_requirement_modification(message):
        return False
    return True


def _normalize_label_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _singularize_label_phrase(text: str) -> str:
    words = _normalize_label_phrase(text).split()
    normalized: list[str] = []
    for word in words:
        if len(word) > 1 and word.endswith("s") and not word.endswith("ss"):
            normalized.append(word[:-1])
        else:
            normalized.append(word)
    return " ".join(normalized)


def _labels_match_fuzzy(phrase: str, field_label: str) -> bool:
    left = _normalize_label_phrase(phrase)
    right = _normalize_label_phrase(field_label)
    if left == right:
        return True
    return _singularize_label_phrase(left) == _singularize_label_phrase(right)


def field_id_for_label(label: str, metadata: JiraCreateMetadata) -> str | None:
    raw = label.strip()
    if not raw:
        return None
    if raw in metadata.fields:
        return raw
    lowered = raw.lower()
    for field_id, field in metadata.fields.items():
        if field_id.lower() == lowered or field.label.strip().lower() == lowered:
            return field_id
    for field_id, field in metadata.fields.items():
        if _labels_match_fuzzy(raw, field.label):
            return field_id
    return None


def parse_field_change_command(message: str, metadata: JiraCreateMetadata) -> dict[str, Any]:
    text = message.strip()
    if not text:
        return {}
    for pattern in _FIELD_CHANGE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        field_id = field_id_for_label(match.group("label").strip(), metadata)
        if not field_id:
            continue
        return {field_id: match.group("value").strip()}
    return {}


def looks_like_field_mutation(message: str) -> bool:
    return bool(_FIELD_MUTATION_HINT.search(message.strip()))


def message_matches_field_option(message: str, field_id: str, metadata: JiraCreateMetadata) -> bool:
    field = metadata.fields.get(field_id)
    if not field:
        return False
    text = message.strip()
    if not text:
        return False
    if _exact_option_match(field, text):
        return True
    lowered = text.lower()
    for option in field.options:
        if option.label.strip().lower() == lowered:
            return True
    return False


def extract_followup_field_updates(
    message: str,
    metadata: JiraCreateMetadata,
    *,
    pending_fields: list[PendingAgentField],
    pending_clarification_field_id: str | None,
) -> dict[str, Any]:
    from .jira_create_agent_preprocess import preprocess_user_message

    updates = interpret_field_resolution_reply(
        message,
        metadata,
        pending_fields=pending_fields,
        pending_clarification_field_id=pending_clarification_field_id,
    )
    if updates:
        return updates
    preprocessed = preprocess_user_message(message, metadata)
    if preprocessed.provided_fields:
        return dict(preprocessed.provided_fields)
    return {}


def coupled_patch_field_ids(patch_keys: set[str], metadata: JiraCreateMetadata) -> set[str]:
    expanded = set(patch_keys)
    if any(
        metadata.fields.get(field_id) and metadata.fields[field_id].type == "parent" for field_id in patch_keys
    ):
        for field_id, field in metadata.fields.items():
            if field.type == "parent":
                expanded.add(field_id)
    return expanded


def merge_field_patch(
    metadata: JiraCreateMetadata,
    current: dict[str, Any],
    resolved: dict[str, Any],
    patch_keys: set[str],
    user_edited: set[str],
) -> dict[str, Any]:
    from .jira_create_validation import merge_agent_fields

    expanded = coupled_patch_field_ids(patch_keys, metadata)
    proposed = {key: resolved[key] for key in expanded if key in resolved and not field_is_empty(resolved.get(key))}
    merged = merge_agent_fields(metadata, current, proposed, user_edited)
    for key in ("summary", "description"):
        if key not in expanded and not field_is_empty(current.get(key)):
            merged[key] = current[key]
    return merged


def interpret_field_resolution_reply(
    message: str,
    metadata: JiraCreateMetadata,
    *,
    pending_fields: list[PendingAgentField],
    pending_clarification_field_id: str | None,
) -> dict[str, Any]:
    text = message.strip()
    if not text:
        return {}

    command_updates = parse_field_change_command(text, metadata)
    if command_updates:
        return command_updates

    pending = list(pending_fields)
    if pending_clarification_field_id and not any(item.field_id == pending_clarification_field_id for item in pending):
        pending.append(PendingAgentField(field_id=pending_clarification_field_id))

    option_hits = [item.field_id for item in pending if message_matches_field_option(text, item.field_id, metadata)]
    if len(option_hits) == 1:
        return {option_hits[0]: text}

    if len(pending) == 1:
        return {pending[0].field_id: text}

    if pending_clarification_field_id and pending_clarification_field_id in metadata.fields:
        return {pending_clarification_field_id: text}

    user_fields = [
        item.field_id
        for item in pending
        if metadata.fields.get(item.field_id) and metadata.fields[item.field_id].type == "user"
    ]
    if len(user_fields) == 1 and len(text.split()) <= 3:
        return {user_fields[0]: text}

    return {}


def build_pending_fields(
    missing: list[MissingRequiredField],
    *,
    prior: list[PendingAgentField],
    raw_field_values: dict[str, Any],
) -> list[PendingAgentField]:
    prior_by_id = {item.field_id: item for item in prior}
    pending: list[PendingAgentField] = []
    for item in missing:
        if item.id in {"__clarification__", "summary", "description"} or item.id.startswith("__"):
            continue
        requested = raw_field_values.get(item.id)
        if field_is_empty(requested) and item.id in prior_by_id:
            requested = prior_by_id[item.id].requested_value
        pending.append(
            PendingAgentField(
                field_id=item.id,
                requested_value=None if field_is_empty(requested) else str(requested),
            )
        )
    return pending


def merge_preserving_requirement(
    metadata: JiraCreateMetadata,
    current: dict[str, Any],
    proposed: dict[str, Any],
    user_edited: set[str],
    *,
    lock_summary_description: bool,
) -> dict[str, Any]:
    from .jira_create_validation import merge_agent_fields

    merged = merge_agent_fields(metadata, current, proposed, user_edited)
    if not lock_summary_description:
        return merged
    for key in ("summary", "description"):
        if not field_is_empty(current.get(key)):
            merged[key] = current[key]
    return merged


def response_conversation_phase(status: str, merged_values: dict[str, Any]) -> AgentConversationPhase:
    if status == "ready":
        return "ready_to_create"
    if not field_is_empty(merged_values.get("summary")) and not field_is_empty(merged_values.get("description")):
        return "field_resolution"
    return "initial_requirement"
