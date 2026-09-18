from abc import ABC, abstractmethod
import logging

import httpx
from fastapi import HTTPException

from .config import Settings

logger = logging.getLogger(__name__)


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


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    def __init__(self, settings: Settings, model: str | None = None, max_tokens: int | None = None) -> None:
        self.api_key = settings.groq_api_key
        self.model = model or settings.groq_model
        self.max_tokens = max_tokens

    def _request_body(self, prompt: str) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
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
            text = message.get("content")
            if not isinstance(text, str) or not text.strip():
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
    def __init__(self, settings: Settings, model: str | None = None) -> None:
        self.api_key = settings.gemini_api_key
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


class ModelGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def provider(self, provider_name: str, model: str | None = None, max_tokens: int | None = None) -> LLMProvider:
        if provider_name == "groq":
            return GroqProvider(self.settings, model, max_tokens)
        if provider_name == "gemini":
            return GeminiProvider(self.settings, model)
        if provider_name in {"openai", "anthropic", "ollama"}:
            return UnconfiguredProvider(provider_name.title())
        raise HTTPException(status_code=400, detail=f"Unknown model provider: {provider_name}")

    async def available_models(self, name: str) -> list[str]:
        if name == "groq" and self.settings.groq_api_key:
            return [self.settings.groq_model_low or self.settings.groq_model, self.settings.groq_model_high or self.settings.groq_model]
        if name == "gemini" and self.settings.gemini_api_key:
            return [self.settings.gemini_model_low or self.settings.gemini_model, self.settings.gemini_model_high or self.settings.gemini_model]
        return []
