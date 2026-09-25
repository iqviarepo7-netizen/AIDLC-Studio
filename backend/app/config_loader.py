from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env(value: Any) -> Any:
    if isinstance(value, str):
        def replacer(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), "")

        return ENV_PATTERN.sub(replacer, value)
    if isinstance(value, dict):
        return {key: _substitute_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_env(item) for item in value]
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return _substitute_env(raw)


class AutomationConfig(BaseModel):
    mode: str = "full"
    auto_start: bool = True
    require_model_selection: bool = True
    max_retries: int = 2
    retry_on: list[str] = Field(default_factory=lambda: ["validation_fail", "implementation_fail"])


class WorkflowConfig(BaseModel):
    store_path: str = "backend/data/workflows.json"
    default_base_branch: str = ""


class LLMKeyChainEntry(BaseModel):
    id: str
    provider: str
    env_var: str


class ModelRoute(BaseModel):
    complexity_min: int
    complexity_max: int
    provider: str
    model: str
    max_tokens: int


class ModelRoutingConfig(BaseModel):
    routes: list[ModelRoute] = Field(default_factory=list, alias="model_routing")
    retry_escalation: str = "next_tier"

    model_config = {"populate_by_name": True}


class MCPServerTools(BaseModel):
    fetch_issue: str = "get_issue"
    transition: str = "transition_issue"
    comment: str = "add_comment"
    analyze: str = "analyze_repository"
    branch: str = "create_branch"
    write: str = "write_files"
    push: str = "push_branch"
    pr: str = "create_pull_request"


class MCPServerConfig(BaseModel):
    server_url: str = ""
    auth_token: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    tools: MCPServerTools = Field(default_factory=MCPServerTools)


class MCPConfig(BaseModel):
    jira: MCPServerConfig = Field(default_factory=MCPServerConfig)
    git: MCPServerConfig = Field(default_factory=MCPServerConfig)


class ValidationCommand(BaseModel):
    id: str
    cmd: list[str]


class ValidationConfig(BaseModel):
    commands: list[ValidationCommand] = Field(default_factory=list)
    fail_fast: bool = True
    timeout_seconds: int = 120


class JiraPublishConfig(BaseModel):
    transition_id: str = ""
    comment_template: str = "PR created: {pr_url}"


class GuardrailsConfig(BaseModel):
    strict: bool = True
    max_file_bytes: int = 102400
    blocked_path_segments: list[str] = Field(default_factory=list)
    stage_tools: dict[str, list[str]] = Field(default_factory=dict)


class PolicyConfig(BaseModel):
    automation: AutomationConfig = Field(default_factory=AutomationConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    model_routing: list[ModelRoute] = Field(default_factory=list)
    llm_key_chain: list[LLMKeyChainEntry] = Field(default_factory=list)
    retry_escalation: str = "next_tier"
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    jira_publish: JiraPublishConfig = Field(default_factory=JiraPublishConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)


class AgentsConfig(BaseModel):
    agents: dict[str, Any] = Field(default_factory=dict)


class UIConfig(BaseModel):
    app: dict[str, str] = Field(default_factory=dict)
    theme: dict[str, str] = Field(default_factory=dict)
    stages: list[dict[str, str]] = Field(default_factory=list)


class AppConfig(BaseModel):
    policy: PolicyConfig
    agents: AgentsConfig
    ui: UIConfig
    config_dir: Path = CONFIG_DIR

    def resolve_path(self, relative: str) -> Path:
        return (self.config_dir / relative).resolve()

    def load_prompt(self, relative_path: str) -> str:
        path = self.resolve_path(relative_path)
        return path.read_text(encoding="utf-8")

    def public_ui_config(self) -> dict[str, Any]:
        return {
            "app": self.ui.app,
            "theme": self.ui.theme,
            "stages": self.ui.stages,
            "automation_mode": self.policy.automation.mode,
            "require_model_selection": self.policy.automation.require_model_selection,
            "default_base_branch": self.policy.workflow.default_base_branch,
        }


@lru_cache
def load_app_config() -> AppConfig:
    policy_raw = _load_yaml(CONFIG_DIR / "policy.yaml")
    agents_raw = _load_yaml(CONFIG_DIR / "agents.yaml")
    ui_raw = _load_yaml(CONFIG_DIR / "ui.yaml")
    return AppConfig(
        policy=PolicyConfig.model_validate(policy_raw),
        agents=AgentsConfig.model_validate(agents_raw),
        ui=UIConfig.model_validate(ui_raw),
    )
