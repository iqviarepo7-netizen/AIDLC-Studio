from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from fastapi import HTTPException

from .config import Settings
from .config_loader import AppConfig, LLMKeyChainEntry
from .models import LLMFailoverEvent, Workflow

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

HTTP_STATUS_IN_DETAIL = re.compile(r"http (\d{3})", re.IGNORECASE)


def _provider_error_detail(provider: str, response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or error.get("type")
            if message:
                return f"{provider} generation failed: HTTP {response.status_code} — {message}"
    except (ValueError, TypeError):
        pass
    body = response.text.strip()[:240]
    if body:
        return f"{provider} generation failed: HTTP {response.status_code} — {body}"
    return f"{provider} generation failed: HTTP {response.status_code}."


def classify_llm_failover_reason(exc: Exception) -> str | None:
    """Return a failover reason code, or None if the error should not trigger key failover."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"

    status: int | None = None
    detail = ""

    if isinstance(exc, HTTPException):
        status = exc.status_code
        detail = str(exc.detail).lower()
    elif isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detail = (exc.response.text or "").lower()

    if detail:
        match = HTTP_STATUS_IN_DETAIL.search(detail)
        if match:
            status = int(match.group(1))

    if status in {401, 403}:
        return "invalid_key"
    if status == 429:
        if any(token in detail for token in ("quota", "credit", "billing", "exhaust")):
            return "quota_exceeded"
        return "rate_limit"
    if status == 402:
        return "quota_exceeded"
    if status in {408, 504}:
        return "timeout"
    if status in {500, 502, 503}:
        if status == 502 and not any(token in detail for token in ("timeout", "unavailable", "overloaded", "503", "502")):
            return None
        return "unavailable"

    if status and status >= 500:
        return "unavailable"

    if isinstance(exc, HTTPException) and exc.status_code == 503 and "not configured" in detail:
        return "invalid_key"

    if status == 404 and any(token in detail for token in ("model", "does not exist", "not found", "not have access")):
        return "model_unavailable"

    if status == 400 and "tool choice" in detail:
        return None

    return None


def extract_groq_message_text(message: dict[str, object]) -> str | None:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict):
                arguments = function.get("arguments")
                if isinstance(arguments, str) and arguments.strip():
                    return arguments
    return None


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    def __init__(
        self,
        settings: Settings,
        model: str | None = None,
        max_tokens: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.model = model or settings.groq_model
        self.max_tokens = max_tokens

    def _request_body(self, prompt: str) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        return body

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="Groq is not configured. Set GROQ_API_KEY, then retry.")
        url = "https://api.groq.com/openai/v1/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=self._request_body(prompt),
                )
            if response.status_code >= 400:
                detail = _provider_error_detail("Groq", response)
                logger.warning("groq_request_failed model=%s status=%s body=%s", self.model, response.status_code, response.text[:500])
                raise HTTPException(status_code=502, detail=detail)
            choices = response.json().get("choices", [])
            message = choices[0].get("message", {}) if choices else {}
            if not isinstance(message, dict):
                message = {}
            text = extract_groq_message_text(message)
            if not text:
                raise ValueError("Groq returned no text content")
            return text
        except HTTPException:
            raise
        except httpx.HTTPStatusError as exc:
            detail = _provider_error_detail("Groq", exc.response)
            logger.warning("groq_request_failed model=%s status=%s body=%s", self.model, exc.response.status_code, exc.response.text[:500])
            raise HTTPException(status_code=502, detail=detail) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("groq_request_failed model=%s error=%s", self.model, exc)
            raise HTTPException(status_code=502, detail=f"Groq generation failed: {exc}") from exc

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            await self.generate("Reply with the word ready.")
            return True
        except HTTPException:
            return False


class GeminiProvider(LLMProvider):
    def __init__(self, settings: Settings, model: str | None = None, api_key: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model = model or settings.gemini_model

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="Gemini is not configured. Set GEMINI_API_KEY, then retry.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers={"x-goog-api-key": self.api_key}, json={"contents": [{"parts": [{"text": prompt}]}]})
            response.raise_for_status()
            candidates = response.json().get("candidates", [])
            text = candidates[0]["content"]["parts"][0]["text"] if candidates else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Gemini returned no text content")
            return text
        except httpx.HTTPStatusError as exc:
            detail = _provider_error_detail("Gemini", exc.response)
            logger.warning("gemini_request_failed model=%s status=%s body=%s", self.model, exc.response.status_code, exc.response.text[:500])
            raise HTTPException(status_code=502, detail=detail) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Gemini generation failed: {exc}") from exc

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            await self.generate("Reply with the word ready.")
            return True
        except HTTPException:
            return False


class UnconfiguredProvider(LLMProvider):
    def __init__(self, name: str) -> None:
        self.name = name

    async def generate(self, prompt: str) -> str:
        raise HTTPException(status_code=503, detail=f"{self.name} provider is connector-ready but not configured.")

    async def health_check(self) -> bool:
        return False


FailoverCallback = Callable[[Workflow, LLMFailoverEvent], None]


class FailoverLLMProvider(LLMProvider):
    def __init__(
        self,
        gateway: ModelGateway,
        workflow: Workflow,
        preferred_provider: str,
        model: str | None,
        max_tokens: int | None,
        on_failover: FailoverCallback | None = None,
    ) -> None:
        self.gateway = gateway
        self.workflow = workflow
        self.preferred_provider = preferred_provider
        self.model = model
        self.max_tokens = max_tokens
        self.on_failover = on_failover

    async def generate(self, prompt: str) -> str:
        chain = self.gateway.resolved_key_chain()
        if not chain:
            provider = self.gateway._base_provider(self.preferred_provider, self.model, self.max_tokens, None)
            return await provider.generate(prompt)

        start = min(max(self.workflow.active_llm_key_index, 0), len(chain) - 1) if chain else 0
        index = start
        last_exc: Exception | None = None
        fallback_model: str | None = None

        while index < len(chain):
            entry = chain[index]
            api_key = self.gateway.resolve_key(entry)
            if not api_key:
                index += 1
                continue

            provider_name = entry.provider
            if fallback_model and provider_name == self.preferred_provider:
                model = fallback_model
                fallback_model = None
            else:
                model = self.model if provider_name == self.preferred_provider else self.gateway.default_model_for(provider_name)
            provider = self.gateway._base_provider(provider_name, model, self.max_tokens, api_key)

            try:
                text = await provider.generate(prompt)
                self.workflow.active_llm_key_index = index
                if entry.id not in self.workflow.llm_keys_used:
                    self.workflow.llm_keys_used.append(entry.id)
                return text
            except Exception as exc:
                reason = classify_llm_failover_reason(exc)
                if not reason:
                    raise
                last_exc = exc
                next_index = index + 1
                while next_index < len(chain) and not self.gateway.resolve_key(chain[next_index]):
                    next_index += 1
                replacement = chain[next_index] if next_index < len(chain) else None
                event = LLMFailoverEvent(
                    timestamp=datetime.now(timezone.utc),
                    failed_key_id=entry.id,
                    failed_provider=entry.provider,
                    reason=reason,
                    replacement_key_id=replacement.id if replacement else None,
                    replacement_provider=replacement.provider if replacement else None,
                    resume_stage=self.workflow.current_stage,
                )
                logger.warning(
                    "llm_key_failover workflow_id=%s failed_key=%s reason=%s replacement=%s stage=%s",
                    self.workflow.id,
                    entry.id,
                    reason,
                    replacement.id if replacement else None,
                    self.workflow.current_stage,
                )
                if self.on_failover:
                    self.on_failover(self.workflow, event)
                if replacement is None:
                    break
                if reason == "model_unavailable" and provider_name == self.preferred_provider:
                    fallback_model = self.gateway.default_model_for(provider_name)
                if reason in {"rate_limit", "quota_exceeded"}:
                    await asyncio.sleep(1.0)
                self.workflow.active_llm_key_index = next_index
                index = next_index

        detail = str(last_exc.detail) if isinstance(last_exc, HTTPException) else str(last_exc)
        raise HTTPException(status_code=502, detail=f"All configured LLM API keys failed. Last error: {detail}")

    async def health_check(self) -> bool:
        chain = self.gateway.resolved_key_chain()
        if not chain:
            return await self.gateway._base_provider(self.preferred_provider, self.model, self.max_tokens, None).health_check()
        for entry in chain:
            api_key = self.gateway.resolve_key(entry)
            if not api_key:
                continue
            provider = self.gateway._base_provider(entry.provider, self.model, self.max_tokens, api_key)
            if await provider.health_check():
                return True
        return False


class ModelGateway:
    def __init__(self, settings: Settings, config: AppConfig | None = None) -> None:
        self.settings = settings
        self.config = config
        self._chain_cache: list[LLMKeyChainEntry] | None = None

    def resolved_key_chain(self) -> list[LLMKeyChainEntry]:
        if self._chain_cache is not None:
            return self._chain_cache
        entries: list[LLMKeyChainEntry] = []
        if self.config and self.config.policy.llm_key_chain:
            entries = list(self.config.policy.llm_key_chain)
        if not entries:
            if self.settings.groq_api_key:
                entries.append(LLMKeyChainEntry(id="groq_key_1", provider="groq", env_var="GROQ_API_KEY"))
            if self.settings.gemini_api_key:
                entries.append(LLMKeyChainEntry(id="gemini_key_1", provider="gemini", env_var="GEMINI_API_KEY"))
        self._chain_cache = [entry for entry in entries if self.resolve_key(entry)]
        return self._chain_cache

    def resolve_key(self, entry: LLMKeyChainEntry) -> str | None:
        value = os.environ.get(entry.env_var, "").strip()
        if value:
            return value
        settings_map: dict[str, str | None] = {
            "GROQ_API_KEY": self.settings.groq_api_key,
            "GROQ_API_KEY_2": self.settings.groq_api_key_2,
            "GROQ_API_KEY_3": self.settings.groq_api_key_3,
            "GEMINI_API_KEY": self.settings.gemini_api_key,
            "GEMINI_API_KEY_2": self.settings.gemini_api_key_2,
            "GEMINI_API_KEY_3": self.settings.gemini_api_key_3,
        }
        fallback = settings_map.get(entry.env_var)
        if fallback and str(fallback).strip():
            return str(fallback).strip()
        return None

    def default_model_for(self, provider_name: str) -> str:
        if provider_name == "groq":
            return self.settings.groq_model
        if provider_name == "gemini":
            return self.settings.gemini_model
        return self.settings.groq_model

    def _base_provider(
        self,
        provider_name: str,
        model: str | None,
        max_tokens: int | None,
        api_key: str | None,
    ) -> LLMProvider:
        if provider_name == "groq":
            return GroqProvider(self.settings, model, max_tokens, api_key)
        if provider_name == "gemini":
            return GeminiProvider(self.settings, model, api_key)
        if provider_name in {"openai", "anthropic", "ollama"}:
            return UnconfiguredProvider(provider_name.title())
        raise HTTPException(status_code=400, detail=f"Unknown model provider: {provider_name}")

    def provider(
        self,
        provider_name: str,
        model: str | None = None,
        max_tokens: int | None = None,
        workflow: Workflow | None = None,
        on_failover: FailoverCallback | None = None,
    ) -> LLMProvider:
        chain = self.resolved_key_chain() if workflow is not None else []
        use_failover = workflow is not None and bool(chain)
        if use_failover:
            return FailoverLLMProvider(self, workflow, provider_name, model, max_tokens, on_failover)
        return self._base_provider(provider_name, model, max_tokens, None)

    def first_resolved_key(self, provider: str) -> str | None:
        for entry in self.resolved_key_chain():
            if entry.provider == provider:
                key = self.resolve_key(entry)
                if key:
                    return key
        if provider == "groq" and self.settings.groq_api_key:
            return self.settings.groq_api_key
        if provider == "gemini" and self.settings.gemini_api_key:
            return self.settings.gemini_api_key
        return None

    async def discover_models(self, provider: str) -> list[dict[str, object]]:
        if provider != "groq":
            raise HTTPException(status_code=400, detail=f"Model discovery is not supported for provider: {provider}")
        api_key = self.first_resolved_key("groq")
        if not api_key:
            raise HTTPException(status_code=503, detail="Groq is not configured.")
        url = "https://api.groq.com/openai/v1/models"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=_provider_error_detail("Groq", response))
        data = response.json().get("data", [])
        models: list[dict[str, object]] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                model_id = item.get("id")
                if not isinstance(model_id, str):
                    continue
                models.append(
                    {
                        "provider": "groq",
                        "id": model_id,
                        "display_name": model_id,
                        "owned_by": item.get("owned_by"),
                        "active": item.get("active", True),
                    }
                )
        models.sort(key=lambda row: str(row.get("id", "")))
        return models

    def configuration_snapshot(self) -> dict[str, object]:
        routes = []
        if self.config:
            for route in self.config.policy.model_routing:
                routes.append(
                    {
                        "complexity_min": route.complexity_min,
                        "complexity_max": route.complexity_max,
                        "provider": route.provider,
                        "model": route.model,
                        "max_tokens": route.max_tokens,
                    }
                )
        return {
            "providers": {
                "groq": {
                    "configured_models": {
                        "default": self.settings.groq_model,
                        "low": self.settings.groq_model_low,
                        "medium": self.settings.groq_model_medium,
                        "high": self.settings.groq_model_high,
                    },
                    "key_chain_ids": [entry.id for entry in self.resolved_key_chain() if entry.provider == "groq"],
                },
                "gemini": {
                    "configured_models": {
                        "default": self.settings.gemini_model,
                        "low": self.settings.gemini_model_low,
                        "medium": self.settings.gemini_model_medium,
                        "high": self.settings.gemini_model_high,
                    },
                    "key_chain_ids": [entry.id for entry in self.resolved_key_chain() if entry.provider == "gemini"],
                },
            },
            "model_routing": routes,
            "llm_key_chain_order": [entry.id for entry in self.resolved_key_chain()],
        }

    async def available_models(self, name: str) -> list[str]:
        has_groq = bool(self.settings.groq_api_key) or any(
            entry.provider == "groq" and self.resolve_key(entry) for entry in (self.config.policy.llm_key_chain if self.config else [])
        )
        has_gemini = bool(self.settings.gemini_api_key) or any(
            entry.provider == "gemini" and self.resolve_key(entry) for entry in (self.config.policy.llm_key_chain if self.config else [])
        )
        if name == "groq" and has_groq:
            return [self.settings.groq_model_low or self.settings.groq_model, self.settings.groq_model_high or self.settings.groq_model]
        if name == "gemini" and has_gemini:
            return [self.settings.gemini_model_low or self.settings.gemini_model, self.settings.gemini_model_high or self.settings.gemini_model]
        return []
