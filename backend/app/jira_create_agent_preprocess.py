from __future__ import annotations

import re
from dataclasses import dataclass, field

from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS
from .jira_create_models import JiraCreateMetadata


@dataclass
class LinkedWorkItemIntent:
    relationship_intent: str
    target_intent: str


@dataclass
class PreprocessedUserPrompt:
    requirement: str
    provided_fields: dict[str, str] = field(default_factory=dict)
    linked_work_items: list[LinkedWorkItemIntent] = field(default_factory=list)


_ASSIGN_PATTERNS = (
    re.compile(r"(?i)\bassign\s+it\s+to\s+([^.;]+)"),
    re.compile(r"(?i)\bassign(?:ed)?(?:\s+to)?(?:\s+as)?\s+([^.;]+)"),
    re.compile(r"(?i)\bassignee\s*[:=]\s*([^.;]+)"),
)

_PRIORITY_PATTERNS = (
    re.compile(r"(?i)\bpriority\s+is\s+([^.;]+)"),
    re.compile(r"(?i)\bpriority\s+should\s+be\s+([^.;]+)"),
    re.compile(r"(?i)\bpriority\s*[:=]\s*([^.;]+)"),
)

_ACTIVE_SPRINT_PATTERN = re.compile(
    r"(?i)\bmark(?:\s+it)?\s+as\s+active\s+sprint\b|\bmark\s+active\s+sprint\b|\bactive\s+sprint\b"
)
_FUTURE_SPRINT_PATTERN = re.compile(
    r"(?i)\bmark(?:\s+it)?\s+as\s+future\s+sprint\b|\bmark\s+future\s+sprint\b|\bfuture\s+sprint\b"
)

_PARENT_PATTERNS = (
    re.compile(r"(?i)\bparent(?:\s+jira)?(?:\s+issue)?\s+(?:is\s+|:\s*|=\s*)?([^.;]+)"),
    re.compile(r"(?i)\bparent\s*[:=]\s*([^.;]+)"),
)

_STORY_POINT_PATTERN = re.compile(r"(?i)\bstory\s+points?\s+(?:is\s+|are\s+|=\s*|:\s*)?(\d+(?:\.\d+)?)")

_LINKED_WORK_ITEM_PATTERNS = (
    re.compile(
        r"(?i)\blinked\s+work\s+items?\s+(?:is|are)\s+(?:that\s+)?this(?:\s+jira)?\s+issue\s+(\w+)\s+([^.;]+)"
    ),
    re.compile(r"(?i)\bthis(?:\s+jira)?\s+issue\s+(\w+)\s+([A-Za-z][A-Za-z0-9]*[\s-]\d+)"),
)

_VALUE_PREFIX_RE = re.compile(r"(?i)^(as|is|should\s+be|to|that)\s+")


def _normalize_requirement_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = re.sub(r"(?:\s*\.)+", ".", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}."
    return cleaned


def _clean_captured_value(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'")
    cleaned = _VALUE_PREFIX_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"(?i)^(jira|issue)\s+is\s+", "", cleaned).strip()
    return cleaned.strip(" ,")


def _field_extraction_patterns(metadata: JiraCreateMetadata) -> list[tuple[str, re.Pattern[str]]]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for field_id, parsed in metadata.fields.items():
        if field_id in CONTEXT_MANAGED_FIELD_IDS:
            continue
        if field_id in {"summary", "description"}:
            continue
        label = parsed.label.strip()
        if not label:
            continue
        label_pattern = re.compile(
            rf"(?i)\b{re.escape(label)}\s*(?:[:=]|is|as|should\s+be)\s+([^.;]+?)(?:\.|$|\s+and\s+)",
        )
        patterns.append((field_id, label_pattern))
        lowered = label.lower()
        if "assignee" in lowered or field_id == "assignee":
            for pattern in _ASSIGN_PATTERNS:
                patterns.append((field_id, pattern))
        elif "reporter" in lowered or field_id == "reporter":
            patterns.append(
                (
                    field_id,
                    re.compile(r"(?i)\breporter\s*[:=]\s*([^.;]+)"),
                )
            )
        elif "priority" in lowered or field_id == "priority":
            for pattern in _PRIORITY_PATTERNS:
                patterns.append((field_id, pattern))
        elif parsed.type == "labels" or field_id == "labels":
            patterns.append(
                (
                    field_id,
                    re.compile(r"(?i)\b(?:add\s+)?labels?\s+([^.;]+)"),
                )
            )
        elif parsed.type in {"date", "datetime"}:
            patterns.append(
                (
                    field_id,
                    re.compile(
                        rf"(?i)\b{re.escape(label)}\s+(?:should\s+be\s+|is\s+|as\s+)?([^.;]+)",
                    ),
                )
            )
            patterns.append(
                (
                    field_id,
                    re.compile(rf"(?i)\bchange\s+{re.escape(label)}\s+to\s+([^.;]+)"),
                )
            )
        elif "parent" in lowered or field_id == "parent":
            for pattern in _PARENT_PATTERNS:
                patterns.append((field_id, pattern))
        elif "sprint" in lowered:
            patterns.append(
                (
                    field_id,
                    re.compile(r"(?i)\bsprint\s*[:=]\s*([^.;]+)"),
                )
            )
            patterns.append(
                (
                    field_id,
                    re.compile(rf"(?i)\bchange\s+{re.escape(label)}\s+to\s+([^.;]+)"),
                )
            )
            patterns.append((field_id, _ACTIVE_SPRINT_PATTERN))
            patterns.append((field_id, _FUTURE_SPRINT_PATTERN))
        elif "story point" in lowered:
            patterns.append((field_id, _STORY_POINT_PATTERN))
    return patterns


def _fixed_capture_value(pattern: re.Pattern[str]) -> str | None:
    if pattern is _ACTIVE_SPRINT_PATTERN:
        return "active sprint"
    if pattern is _FUTURE_SPRINT_PATTERN:
        return "future sprint"
    return None


def _capture_value(match: re.Match[str], *, fixed: str | None = None) -> str:
    if fixed is not None:
        return fixed
    if match.lastindex and match.lastindex >= 1:
        return _clean_captured_value(match.group(1))
    return _clean_captured_value(match.group(0))


def _extract_linked_work_items(text: str) -> tuple[list[LinkedWorkItemIntent], list[tuple[int, int]]]:
    items: list[LinkedWorkItemIntent] = []
    spans: list[tuple[int, int]] = []
    for pattern in _LINKED_WORK_ITEM_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if any(start <= span[0] and span[1] <= end for start, end in spans):
                continue
            relationship = _clean_captured_value(match.group(1))
            target = _clean_captured_value(match.group(2))
            if not relationship and not target:
                continue
            items.append(LinkedWorkItemIntent(relationship_intent=relationship, target_intent=target))
            spans.append(span)
    return items, spans


def preprocess_user_message(text: str, metadata: JiraCreateMetadata) -> PreprocessedUserPrompt:
    working = text.strip()
    provided: dict[str, str] = {}
    seen_spans: list[tuple[int, int]] = []

    linked_items, linked_spans = _extract_linked_work_items(working)
    seen_spans.extend(linked_spans)

    for field_id, pattern in _field_extraction_patterns(metadata):
        for match in pattern.finditer(working):
            span = match.span()
            if any(start <= span[0] and span[1] <= end for start, end in seen_spans):
                continue
            value = _capture_value(match, fixed=_fixed_capture_value(pattern))
            if not value:
                continue
            provided[field_id] = value
            seen_spans.append(span)

    requirement_parts: list[str] = []
    last = 0
    for start, end in sorted(seen_spans):
        if start > last:
            requirement_parts.append(working[last:start])
        last = max(last, end)
    if last < len(working):
        requirement_parts.append(working[last:])
    requirement = _normalize_requirement_text(" ".join(part.strip() for part in requirement_parts if part.strip()))
    if not requirement and working:
        requirement = _normalize_requirement_text(working)
    return PreprocessedUserPrompt(
        requirement=requirement,
        provided_fields=provided,
        linked_work_items=linked_items,
    )


def format_preprocessed_for_llm(preprocessed: PreprocessedUserPrompt, metadata: JiraCreateMetadata) -> str:
    lines = ["REQUIREMENT:", preprocessed.requirement or "(none)", "", "USER-PROVIDED JIRA FIELDS:"]
    if not preprocessed.provided_fields and not preprocessed.linked_work_items:
        lines.append("(none)")
    else:
        for field_id, value in preprocessed.provided_fields.items():
            label = metadata.fields[field_id].label if field_id in metadata.fields else field_id
            lines.append(f"{label}: {value}")
        for item in preprocessed.linked_work_items:
            lines.append(
                f"Linked work item: relationship={item.relationship_intent}; target={item.target_intent}"
            )
    return "\n".join(lines)
