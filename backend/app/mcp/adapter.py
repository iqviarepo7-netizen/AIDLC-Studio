from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import HTTPException

from ..config_loader import AppConfig, MCPServerConfig
from ..guardrails import GuardrailViolation, Guardrails, guardrail_http_exception
from ..integrations import direct_git, direct_jira
from ..models import JiraTask, MCPAuditRecord, PullRequest, RepositoryAnalysis, Workflow
from ..session_context import get_current_session
from .clients import ExternalMCPClient
from .tool_map import ToolMap

SECRET_KEYS = {"auth_token", "token", "password", "api_key", "authorization"}


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(payload)
    for key in list(redacted.keys()):
        if key.lower() in SECRET_KEYS:
            redacted[key] = "[redacted]"
        elif isinstance(redacted[key], dict):
            redacted[key] = redact_payload(redacted[key])
    return redacted


@dataclass
class MCPResult:
    data: dict[str, Any]
    duration_ms: int


class MCPAdapter:
    def __init__(self, config: AppConfig, client: ExternalMCPClient | None = None) -> None:
        self.config = config
        self.tool_map = ToolMap(config)
        self.guardrails = Guardrails(config.policy.guardrails)
        self.client = client or ExternalMCPClient()

    async def call_tool(
        self,
        workflow: Workflow,
        *,
        stage: str,
        agent: str,
        server: str,
        tool_key: str,
        arguments: dict[str, Any],
    ) -> MCPResult:
        logical_tool = self.tool_map.logical_name(server, tool_key)
        try:
            self.guardrails.validate_request(stage, logical_tool, arguments)
        except GuardrailViolation as exc:
            self._audit(workflow, agent, server, tool_key, "blocked", 0, arguments, {}, exc.message)
            raise guardrail_http_exception(exc) from exc

        server_config = self._server_config(server)
        tool_name = self.tool_map.resolve(server, tool_key)
        started = perf_counter()
        try:
            response = await self.client.call_tool(server_config, tool_name, arguments)
        except HTTPException as exc:
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, agent, server, tool_key, "error", duration, arguments, {"detail": exc.detail}, "request_failed")
            raise

        duration = int((perf_counter() - started) * 1000)
        try:
            self.guardrails.validate_response(logical_tool, response)
        except GuardrailViolation as exc:
            self._audit(workflow, agent, server, tool_key, "blocked", duration, arguments, response, exc.message)
            raise guardrail_http_exception(exc) from exc

        self._audit(workflow, agent, server, tool_key, "success", duration, arguments, response, None)
        return MCPResult(data=response, duration_ms=duration)

    def _audit(
        self,
        workflow: Workflow,
        agent: str,
        server: str,
        tool: str,
        status: str,
        duration_ms: int,
        request: dict[str, Any],
        response: dict[str, Any],
        guardrail_result: str | None,
    ) -> None:
        workflow.mcp_audit.append(
            MCPAuditRecord(
                timestamp=datetime.now(timezone.utc),
                workflow_id=workflow.id,
                agent=agent,
                server=server,
                tool=tool,
                status=status,
                duration_ms=duration_ms,
                request_redacted=redact_payload(request),
                response_redacted=redact_payload(response if isinstance(response, dict) else {"value": response}),
                guardrail_result=guardrail_result,
            )
        )

    def _server_config(self, server: str) -> MCPServerConfig:
        session = get_current_session()
        base = self.tool_map.server_config(server)
        if server == "jira" and session and session.jira.mode == "mcp":
            return MCPServerConfig(
                server_url=session.jira.mcp_url or base.server_url,
                auth_token=session.jira.mcp_token or base.auth_token,
                tools=base.tools,
            )
        if server == "git" and session and session.git.mode == "mcp":
            return MCPServerConfig(
                server_url=session.git.mcp_url or base.server_url,
                auth_token=session.git.mcp_token or base.auth_token,
                tools=base.tools,
            )
        return base

    async def fetch_issue(self, workflow: Workflow, jira_key: str) -> JiraTask:
        session = get_current_session()
        if session and session.jira.mode == "direct":
            started = perf_counter()
            task = await direct_jira.fetch_issue(session.jira, jira_key)
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, "task_analyzer", "jira", "fetch_issue", "success", duration, {"issue_key": jira_key}, {"summary": task.summary}, None)
            return task
        result = await self.call_tool(
            workflow,
            stage="analyzing",
            agent="task_analyzer",
            server="jira",
            tool_key="fetch_issue",
            arguments={"issue_key": jira_key, "key": jira_key},
        )
        data = result.data
        fields = data.get("fields", data)
        description = fields.get("description")
        if isinstance(description, dict):
            description = " ".join(self._walk_adf(description))
        summary = fields.get("summary") or data.get("summary") or jira_key
        return JiraTask(
            key=jira_key.upper(),
            summary=str(summary),
            description=str(description) if description else None,
            issue_type=(fields.get("issuetype") or {}).get("name", data.get("issue_type", "TASK")),
            priority=(fields.get("priority") or {}).get("name", data.get("priority")),
            acceptance_criteria=list(data.get("acceptance_criteria") or fields.get("acceptance_criteria") or []),
        )

    async def analyze_repository(self, workflow: Workflow, repository_path: str) -> RepositoryAnalysis:
        session = get_current_session()
        if session and session.git.mode == "direct":
            started = perf_counter()
            analysis = direct_git.analyze_repository(session.git, repository_path)
            duration = int((perf_counter() - started) * 1000)
            self._audit(
                workflow,
                "implementation",
                "git",
                "analyze",
                "success",
                duration,
                {"repository_path": repository_path},
                {"project_type": analysis.project_type},
                None,
            )
            return analysis
        result = await self.call_tool(
            workflow,
            stage="implementing",
            agent="implementation",
            server="git",
            tool_key="analyze",
            arguments={"repository_path": repository_path},
        )
        data = result.data
        return RepositoryAnalysis(
            project_type=str(data.get("project_type", "Git repository")),
            relevant_directories=list(data.get("relevant_directories") or ["."]),
            relevant_files=list(data.get("relevant_files") or []),
            test_command=data.get("test_command"),
            notes=str(data.get("notes", "Repository analyzed via Git MCP.")),
        )

    async def create_branch(
        self,
        workflow: Workflow,
        repository_path: str,
        jira_key: str,
        summary: str,
        *,
        base_branch: str | None = None,
        branch_name: str | None = None,
    ) -> str:
        arguments: dict[str, Any] = {
            "repository_path": repository_path,
            "jira_key": jira_key,
            "summary": summary,
        }
        if base_branch:
            arguments["base_branch"] = base_branch
        if branch_name:
            arguments["branch_name"] = branch_name
        session = get_current_session()
        if session and session.git.mode == "direct":
            started = perf_counter()
            branch = direct_git.create_branch(
                session.git,
                repository_path,
                jira_key,
                summary,
                base_branch=base_branch,
                branch_name=branch_name,
            )
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, "implementation", "git", "branch", "success", duration, arguments, {"branch": branch}, None)
            return branch
        result = await self.call_tool(
            workflow,
            stage="implementing",
            agent="implementation",
            server="git",
            tool_key="branch",
            arguments=arguments,
        )
        return str(result.data.get("branch") or result.data.get("name") or branch_name or f"ai/{jira_key.lower()}")

    async def write_files(self, workflow: Workflow, repository_path: str, files: list[dict[str, str]]) -> list[str]:
        session = get_current_session()
        if session and session.git.mode == "direct":
            started = perf_counter()
            changed = direct_git.write_files(repository_path, files)
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, "implementation", "git", "write", "success", duration, {"files": len(files)}, {"changed_files": changed}, None)
            return changed
        result = await self.call_tool(
            workflow,
            stage="implementing",
            agent="implementation",
            server="git",
            tool_key="write",
            arguments={"repository_path": repository_path, "files": files},
        )
        changed = result.data.get("changed_files") or [item.get("path") for item in files if "path" in item]
        return [str(path) for path in changed if path]

    async def push_branch(self, workflow: Workflow, repository_path: str) -> None:
        session = get_current_session()
        branch = workflow.work_branch or (workflow.implementation.branch if workflow.implementation else None)
        if session and session.git.mode == "direct" and branch:
            started = perf_counter()
            direct_git.push_branch(session.git, repository_path, branch)
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, "publisher", "git", "push", "success", duration, {"branch": branch}, {}, None)
            return
        await self.call_tool(
            workflow,
            stage="publishing",
            agent="publisher",
            server="git",
            tool_key="push",
            arguments={"repository_path": repository_path},
        )

    async def create_pull_request(
        self,
        workflow: Workflow,
        repository_path: str,
        title: str,
        body: str,
        *,
        base_branch: str | None = None,
        head_branch: str | None = None,
    ) -> PullRequest:
        arguments: dict[str, Any] = {"repository_path": repository_path, "title": title, "body": body}
        if base_branch:
            arguments["base_branch"] = base_branch
        if head_branch:
            arguments["head_branch"] = head_branch
        session = get_current_session()
        if session and session.git.mode == "direct":
            started = perf_counter()
            pull_request = await direct_git.create_pull_request(
                session.git,
                repository_path,
                title=title,
                body=body,
                base_branch=base_branch or session.git.base_branch or "main",
                head_branch=head_branch or workflow.work_branch or "HEAD",
            )
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, "publisher", "git", "pr", "success", duration, arguments, {"url": pull_request.url}, None)
            return pull_request
        result = await self.call_tool(
            workflow,
            stage="publishing",
            agent="publisher",
            server="git",
            tool_key="pr",
            arguments=arguments,
        )
        data = result.data
        return PullRequest(
            number=int(data.get("number") or data.get("pull_request_number") or 0),
            title=str(data.get("title") or title),
            url=str(data.get("url") or data.get("html_url") or ""),
            status=str(data.get("status") or data.get("state") or "OPEN").upper(),
        )

    async def transition_issue(self, workflow: Workflow, jira_key: str, transition_id: str) -> None:
        session = get_current_session()
        if session and session.jira.mode == "direct":
            started = perf_counter()
            await direct_jira.transition_issue(session.jira, jira_key, transition_id)
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, "publisher", "jira", "transition", "success", duration, {"issue_key": jira_key}, {}, None)
            return
        await self.call_tool(
            workflow,
            stage="publishing",
            agent="publisher",
            server="jira",
            tool_key="transition",
            arguments={"issue_key": jira_key, "transition_id": transition_id},
        )

    async def comment_issue(self, workflow: Workflow, jira_key: str, comment: str) -> None:
        session = get_current_session()
        if session and session.jira.mode == "direct":
            started = perf_counter()
            await direct_jira.comment_issue(session.jira, jira_key, comment)
            duration = int((perf_counter() - started) * 1000)
            self._audit(workflow, "publisher", "jira", "comment", "success", duration, {"issue_key": jira_key}, {}, None)
            return
        await self.call_tool(
            workflow,
            stage="publishing",
            agent="publisher",
            server="jira",
            tool_key="comment",
            arguments={"issue_key": jira_key, "comment": comment, "body": comment},
        )

    @staticmethod
    def _walk_adf(value: object) -> list[str]:
        if isinstance(value, dict):
            parts = [part for child in value.get("content", []) for part in MCPAdapter._walk_adf(child)]
            if isinstance(value.get("text"), str):
                parts.append(value["text"])
            return parts
        if isinstance(value, list):
            return [part for child in value for part in MCPAdapter._walk_adf(child)]
        return []
