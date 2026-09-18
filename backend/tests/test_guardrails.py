import pytest

from app.config_loader import load_app_config
from app.guardrails import Guardrails, GuardrailViolation


def test_stage_tool_allowlist_blocks_publish_tool_during_analyze() -> None:
    config = load_app_config()
    guardrails = Guardrails(config.policy.guardrails)
    with pytest.raises(GuardrailViolation):
        guardrails.validate_request("analyzing", "git.push", {"repository_path": "/tmp/repo"})


def test_guardrail_blocks_oversized_file_response() -> None:
    config = load_app_config()
    guardrails = Guardrails(config.policy.guardrails)
    with pytest.raises(GuardrailViolation):
        guardrails.validate_response("git.write", {"files": [{"path": "app/main.py", "content": "x" * 200000}]})
