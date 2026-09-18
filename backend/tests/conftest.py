import os

import pytest

from app.config_loader import load_app_config


@pytest.fixture(autouse=True)
def configure_test_env() -> None:
    os.environ.setdefault("GROQ_MODEL_LOW", "llama-3.1-8b-instant")
    os.environ.setdefault("GROQ_MODEL_MEDIUM", "llama-3.3-70b-versatile")
    os.environ.setdefault("GROQ_MODEL_HIGH", "llama-3.3-70b-versatile")
    os.environ.setdefault("GEMINI_MODEL_LOW", "gemini-2.5-flash")
    os.environ.setdefault("GEMINI_MODEL_MEDIUM", "gemini-2.5-flash")
    os.environ.setdefault("GEMINI_MODEL_HIGH", "gemini-2.5-pro")
    load_app_config.cache_clear()
    yield
    load_app_config.cache_clear()
