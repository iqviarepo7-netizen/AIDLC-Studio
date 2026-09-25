from __future__ import annotations

import json
import re

from fastapi import HTTPException

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_FENCED_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _fenced_json_candidates(raw: str) -> list[str]:
    out: list[str] = []
    for match in _FENCED_BLOCK.finditer(raw):
        block = match.group(1).strip()
        if block and block not in out:
            out.append(block)
    return out


def _scan_json_object(text: str) -> dict[str, object] | None:
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        char = text[index]
        if char != "{":
            index += 1
            continue
        try:
            payload, _end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(payload, dict):
            return payload
        index += 1
    return None


def parse_llm_json_object(raw: str, *, context: str = "LLM") -> dict[str, object]:
    stripped = raw.strip()
    text = _FENCE.sub("", stripped).strip()
    last_error: json.JSONDecodeError | None = None
    candidates: list[str] = []
    for piece in (*_fenced_json_candidates(stripped), text, stripped):
        if piece and piece not in candidates:
            candidates.append(piece)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError as exc:
            last_error = exc
    for candidate in candidates:
        scanned = _scan_json_object(candidate)
        if scanned is not None:
            return scanned
    detail = f"{context} did not return valid JSON."
    if last_error:
        raise HTTPException(status_code=502, detail=detail) from last_error
    raise HTTPException(status_code=502, detail=detail)
