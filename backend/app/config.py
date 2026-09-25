from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")

    gemini_api_key: str | None = None
    gemini_api_key_2: str | None = None
    gemini_api_key_3: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_model_low: str | None = None
    gemini_model_medium: str | None = None
    gemini_model_high: str | None = None
    groq_api_key: str | None = None
    groq_api_key_2: str | None = None
    groq_api_key_3: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_model_low: str | None = None
    groq_model_medium: str | None = None
    groq_model_high: str | None = None
    groq_fallback_model: str = "llama-3.3-70b-versatile"
    jira_mcp_url: str | None = None
    jira_mcp_token: str | None = None
    git_mcp_url: str | None = None
    git_mcp_token: str | None = None
    jira_done_transition_id: str | None = None
    workflow_store_path: str | None = None
    repository_path: str | None = None
    github_base_branch: str | None = None
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.gemini_model_low:
        object.__setattr__(settings, "gemini_model_low", settings.gemini_model)
    if not settings.gemini_model_medium:
        object.__setattr__(settings, "gemini_model_medium", settings.gemini_model)
    if not settings.gemini_model_high:
        object.__setattr__(settings, "gemini_model_high", settings.gemini_model)
    if not settings.groq_model_low:
        object.__setattr__(settings, "groq_model_low", settings.groq_model)
    if not settings.groq_model_medium:
        object.__setattr__(settings, "groq_model_medium", settings.groq_model)
    if not settings.groq_model_high:
        object.__setattr__(settings, "groq_model_high", settings.groq_model)
    return settings
