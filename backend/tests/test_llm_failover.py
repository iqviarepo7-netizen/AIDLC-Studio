from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.config import Settings, get_settings
from app.config_loader import LLMKeyChainEntry, load_app_config
from app.llm import FailoverLLMProvider, ModelGateway, classify_llm_failover_reason
from app.models import Workflow


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> ModelGateway:
    monkeypatch.setenv("GROQ_API_KEY", "key-one")
    monkeypatch.setenv("GROQ_API_KEY_2", "key-two")
    get_settings.cache_clear()
    load_app_config.cache_clear()
    config = load_app_config()
    gateway = ModelGateway(get_settings(), config)
    gateway._chain_cache = None
    return gateway


def test_classify_rate_limit() -> None:
    exc = HTTPException(status_code=502, detail="Groq generation failed: HTTP 429 — rate limit")
    assert classify_llm_failover_reason(exc) == "rate_limit"


def test_classify_no_failover_on_parse_error() -> None:
    assert classify_llm_failover_reason(ValueError("bad json")) is None


@pytest.mark.asyncio
async def test_failover_switches_key_and_records_event(gateway: ModelGateway) -> None:
    workflow = Workflow(jira_key="DEMO-1")
    workflow.current_stage = "plan"
    events: list = []

    provider = FailoverLLMProvider(
        gateway,
        workflow,
        "groq",
        "llama-3.3-70b-versatile",
        1000,
        on_failover=lambda wf, event: events.append(event),
    )

    first = AsyncMock(side_effect=HTTPException(status_code=502, detail="Groq generation failed: HTTP 429 — rate limit"))
    second = AsyncMock(return_value="ok plan")

    call_count = {"n": 0}

    def fake_base(provider_name: str, model: str | None, max_tokens: int | None, api_key: str | None) -> AsyncMock:
        call_count["n"] += 1
        mock = AsyncMock()
        mock.generate = first if call_count["n"] == 1 else second
        mock.health_check = AsyncMock(return_value=True)
        return mock

    gateway._base_provider = fake_base  # type: ignore[method-assign]

    result = await provider.generate("prompt")
    assert result == "ok plan"
    assert workflow.active_llm_key_index == 1
    assert "groq_key_2" in workflow.llm_keys_used
    assert len(events) == 1
    assert events[0].failed_key_id == "groq_key_1"
    assert events[0].replacement_key_id == "groq_key_2"
    assert events[0].resume_stage == "plan"


@pytest.mark.asyncio
async def test_failover_exhausted_raises(gateway: ModelGateway) -> None:
    workflow = Workflow(jira_key="DEMO-2")
    provider = FailoverLLMProvider(gateway, workflow, "groq", "llama-3.3-70b-versatile", 1000)

    failing = AsyncMock(side_effect=HTTPException(status_code=502, detail="Groq generation failed: HTTP 429 — rate limit"))

    def fake_base(provider_name: str, model: str | None, max_tokens: int | None, api_key: str | None) -> AsyncMock:
        mock = AsyncMock()
        mock.generate = failing
        return mock

    gateway._base_provider = fake_base  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as exc_info:
        await provider.generate("prompt")
    assert "All configured LLM API keys failed" in str(exc_info.value.detail)
