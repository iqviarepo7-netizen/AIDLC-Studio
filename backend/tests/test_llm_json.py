from fastapi import HTTPException

from app.llm import classify_llm_failover_reason
from app.llm_json import parse_llm_json_object


def test_parse_llm_json_object_extracts_embedded_object() -> None:
    raw = 'Here is the plan:\n{"summary":"ok","files":[{"path":"a.py","content":"x"}]}'
    payload = parse_llm_json_object(raw, context="Test")
    assert payload["summary"] == "ok"


def test_parse_llm_json_object_finds_object_after_prose() -> None:
    raw = 'Notes first.\n{"summary":"done","files":[{"path":"b.py","content":"print(1)"}]} trailing'
    payload = parse_llm_json_object(raw, context="Test")
    assert payload["summary"] == "done"


def test_parse_llm_json_object_prefers_fenced_block() -> None:
    raw = 'Here you go:\n```json\n{"summary":"fenced","files":[{"path":"a.py","content":"x"}]}\n```'
    payload = parse_llm_json_object(raw, context="Test")
    assert payload["summary"] == "fenced"


def test_classify_model_404() -> None:
    exc = HTTPException(status_code=502, detail="Groq generation failed: HTTP 404 — model does not exist")
    assert classify_llm_failover_reason(exc) == "model_unavailable"
