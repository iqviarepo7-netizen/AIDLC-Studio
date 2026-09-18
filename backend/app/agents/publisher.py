from __future__ import annotations

from ..config_loader import AppConfig
from ..mcp.adapter import MCPAdapter
from ..models import PullRequest, Workflow
from ..session_context import get_current_session


class PublisherAgent:
    def __init__(self, config: AppConfig, mcp: MCPAdapter) -> None:
        self.config = config
        self.mcp = mcp

    async def publish(self, workflow: Workflow, repository_path: str) -> PullRequest:
        if not workflow.jira_task:
            raise ValueError("Jira task is required before publishing.")
        await self.mcp.push_branch(workflow, repository_path)
        body = self._build_pr_body(workflow)
        base_branch = workflow.selected_base_branch or (workflow.branch_analysis.base_branch if workflow.branch_analysis else None)
        head_branch = workflow.work_branch or (workflow.implementation.branch if workflow.implementation else None)
        pull_request = await self.mcp.create_pull_request(
            workflow,
            repository_path,
            workflow.jira_task.summary,
            body,
            base_branch=base_branch,
            head_branch=head_branch,
        )
        comment = self._build_jira_comment(workflow, pull_request)
        session = get_current_session()
        transition_id = (session.jira.transition_id if session and session.jira.transition_id else None) or self.config.policy.jira_publish.transition_id
        if transition_id:
            await self.mcp.transition_issue(workflow, workflow.jira_key, transition_id)
        await self.mcp.comment_issue(workflow, workflow.jira_key, comment)
        return pull_request

    def _build_pr_body(self, workflow: Workflow) -> str:
        test_summary = workflow.test_result.summary if workflow.test_result else "Validation completed."
        return f"## {workflow.jira_key}\n\n{workflow.jira_task.summary if workflow.jira_task else workflow.jira_key}\n\n### Validation\n{test_summary}"

    def _build_jira_comment(self, workflow: Workflow, pull_request: PullRequest) -> str:
        template = self.config.policy.jira_publish.comment_template
        return template.format(
            pr_url=pull_request.url,
            summary=workflow.jira_task.summary if workflow.jira_task else workflow.jira_key,
            model=workflow.selected_model or "unknown",
            test_summary=workflow.test_result.summary if workflow.test_result else "Not recorded",
        )
