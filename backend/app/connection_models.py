from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class JiraConnectionConfig(BaseModel):
    mode: Literal["direct", "mcp"] = "mcp"
    base_url: str | None = None
    email: str | None = None
    api_token: str | None = None
    mcp_url: str | None = None
    mcp_token: str | None = None
    transition_id: str | None = None


class GitConnectionConfig(BaseModel):
    mode: Literal["direct", "mcp"] = "mcp"
    repository_path: str | None = None
    base_branch: str | None = None
    remote: str = "origin"
    mcp_url: str | None = None
    mcp_token: str | None = None


class SetupRequest(BaseModel):
    jira: JiraConnectionConfig
    git: GitConnectionConfig


class ConnectionCheckResult(BaseModel):
    ok: bool
    mode: str
    message: str


class SetupSummary(BaseModel):
    jira_mode: str
    git_mode: str
    repository_path: str | None = None
    jira_host: str | None = None
    default_base_branch: str | None = None


class SetupResponse(BaseModel):
    session_id: str
    jira: ConnectionCheckResult
    git: ConnectionCheckResult
    branches: list[str] = Field(default_factory=list)
    default_branch: str = "main"
    summary: SetupSummary


class BranchPreviewRequest(BaseModel):
    repository_path: str


class SessionConnection(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    jira: JiraConnectionConfig
    git: GitConnectionConfig

    def public_summary(self) -> SetupSummary:
        host = None
        if self.jira.mode == "direct" and self.jira.base_url:
            host = self.jira.base_url.rstrip("/").split("//")[-1][:80]
        elif self.jira.mode == "mcp" and self.jira.mcp_url:
            host = self.jira.mcp_url.rstrip("/").split("//")[-1][:80]
        return SetupSummary(
            jira_mode=self.jira.mode,
            git_mode=self.git.mode,
            repository_path=self.git.repository_path,
            jira_host=host,
            default_base_branch=self.git.base_branch,
        )
