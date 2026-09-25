from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.llm import GroqProvider

TOOL_CONFLICT_BODY = {"error": {"message": "Tool choice is none, but model called a tool"}}


def _settings(**overrides: Any) -> Settings:
    base = {"groq_api_key": "test-key", "groq_model": "openai/gpt-oss-20b"}
    base.update(overrides)
    return Settings(**base)


def _transport(responses: list[httpx.Response]) -> tuple[httpx.MockTransport, list[str]]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content)["model"])
        return responses[len(seen) - 1]

    return httpx.MockTransport(handler), seen


@pytest.fixture
def patch_client(monkeypatch: pytest.MonkeyPatch):
    def apply(responses: list[httpx.Response]) -> list[str]:
        transport, seen = _transport(responses)
        original = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = transport
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return seen

    return apply


def _ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.mark.asyncio
async def test_tool_call_conflict_falls_back_to_chat_model(patch_client) -> None:
    seen = patch_client([httpx.Response(400, json=TOOL_CONFLICT_BODY), _ok("generated")])
    provider = GroqProvider(_settings(groq_fallback_model="llama-3.3-70b-versatile"))

    assert await provider.generate("build this") == "generated"
    assert seen == ["openai/gpt-oss-20b", "llama-3.3-70b-versatile"]


@pytest.mark.asyncio
async def test_tool_call_conflict_without_usable_fallback_raises(patch_client) -> None:
    patch_client([httpx.Response(400, json=TOOL_CONFLICT_BODY)])
    provider = GroqProvider(_settings(groq_fallback_model="openai/gpt-oss-20b"))

    with pytest.raises(HTTPException) as error:
        await provider.generate("build this")

    assert "GROQ_FALLBACK_MODEL" in error.value.detail


@pytest.mark.asyncio
async def test_other_errors_are_not_retried(patch_client) -> None:
    seen = patch_client([httpx.Response(401, json={"error": {"message": "Invalid API Key"}})])
    provider = GroqProvider(_settings())

    with pytest.raises(HTTPException) as error:
        await provider.generate("build this")

    assert "Invalid API Key" in error.value.detail
    assert seen == ["openai/gpt-oss-20b"]
