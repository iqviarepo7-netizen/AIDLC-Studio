from __future__ import annotations

from ..models import Workflow, WorkflowReport


class ReportAgent:
    def generate(self, workflow: Workflow) -> WorkflowReport:
        return WorkflowReport(
            jira_key=workflow.jira_key,
            summary=workflow.jira_task.summary if workflow.jira_task else workflow.jira_key,
            complexity_level=workflow.complexity.level if workflow.complexity else "UNKNOWN",
            complexity_score=workflow.complexity.score if workflow.complexity else 0,
            selected_model=workflow.selected_model or "unknown",
            validation_status=workflow.implementation.validation_status if workflow.implementation else "UNKNOWN",
            pr_url=workflow.pull_request.url if workflow.pull_request else None,
            final_status=workflow.state.value,
            retry_count=workflow.retry_count,
        )
