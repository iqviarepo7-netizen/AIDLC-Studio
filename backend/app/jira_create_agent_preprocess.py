from __future__ import annotations

import re
from dataclasses import dataclass, field
from .jira_create_constants import CONTEXT_MANAGED_FIELD_IDS
from .jira_create_models import JiraCreateMetadata


@dataclass
class PreprocessedUserPrompt:
    requirement: str
    provided_fields: dict[str, str] = field(default_factory=dict)


_ASSIGN_PATTERNS = (
    re.compile(r"(?i)\bassign(?:ed)?(?:\s+to)?(?:\s+as)?\s+([^.;]+)"),
    re.compile(r"(?i)\bassignee\s*[:=]\s*([^.;]+)"),
)


def _normalize_requirement_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if cleaned and cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}."
    return cleaned


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
            rf"(?i)\b{re.escape(label)}\s*[:=]\s*([^.;]+?)(?:\.|$|\s+and\s+)",
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
            patterns.append(
                (
                    field_id,
                    re.compile(r"(?i)\bpriority\s*[:=]\s*([^.;]+)"),
                )
            )
        elif "parent" in lowered or field_id == "parent":
            patterns.append(
                (
                    field_id,
                    re.compile(r"(?i)\bparent\s*[:=]\s*([^.;]+)"),
                )
            )
        elif "sprint" in lowered:
            patterns.append(
                (
                    field_id,
                    re.compile(r"(?i)\bsprint\s*[:=]\s*([^.;]+)"),
                )
            )
    return patterns


def preprocess_user_message(text: str, metadata: JiraCreateMetadata) -> PreprocessedUserPrompt:
    working = text.strip()
    provided: dict[str, str] = {}
    seen_spans: list[tuple[int, int]] = []

    for field_id, pattern in _field_extraction_patterns(metadata):
        for match in pattern.finditer(working):
            span = match.span()
            if any(start <= span[0] and span[1] <= end for start, end in seen_spans):
                continue
            value = match.group(1).strip().strip('"').strip("'")
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
    return PreprocessedUserPrompt(requirement=requirement, provided_fields=provided)


def format_preprocessed_for_llm(preprocessed: PreprocessedUserPrompt, metadata: JiraCreateMetadata) -> str:
    lines = ["REQUIREMENT:", preprocessed.requirement or "(none)", "", "USER-PROVIDED JIRA FIELDS:"]
    if not preprocessed.provided_fields:
        lines.append("(none)")
    else:
        for field_id, value in preprocessed.provided_fields.items():
            label = metadata.fields[field_id].label if field_id in metadata.fields else field_id
            lines.append(f"{label}: {value}")
    return "\n".join(lines)
