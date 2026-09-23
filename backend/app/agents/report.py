from __future__ import annotations

from datetime import datetime, timezone

from ..models import (
    ReportBuildSection,
    ReportDeliverySection,
    ReportFailureInfo,
    ReportFileSummary,
    ReportPlanningSection,
    ReportRequirementSection,
    ReportSectionStatus,
    ReportTestingSection,
    Workflow,
    WorkflowReport,
    WorkflowState,
)

SECTION_DEFS: list[tuple[str, str]] = [
    ("requirement", "Requirement Analysis"),
    ("planning", "Planning & Model Selection"),
    ("build", "Implementation"),
    ("testing", "Testing & Validation"),
    ("delivery", "PR & Jira Delivery"),
]

STAGE_TO_SECTION = {
    "fetch_issue": "requirement",
    "plan": "planning",
    "plan_review": "planning",
    "implement": "build",
    "validate": "testing",
    "publish": "delivery",
}

STAGE_LABELS = {
    "fetch_issue": "Analyze",
    "plan": "Plan",
    "plan_review": "Plan",
    "implement": "Build",
    "validate": "Test",
    "publish": "Publish",
}


class ReportAgent:
    def generate(self, workflow: Workflow) -> WorkflowReport:
        duration_ms = None
        if workflow.created_at and workflow.updated_at:
            duration_ms = int((workflow.updated_at - workflow.created_at).total_seconds() * 1000)

        pr_body = None
        jira_comment_posted = False
        jira_transition_posted = False
        for record in workflow.mcp_audit:
            if record.tool == "pr" and not pr_body:
                pr_body = record.request_redacted.get("body")
            if record.server == "jira" and record.tool == "comment" and record.status == "success":
                jira_comment_posted = True
            if record.server == "jira" and record.tool == "transition" and record.status == "success":
                jira_transition_posted = True

        latest_plan = workflow.plans[-1] if workflow.plans else None
        file_summaries = [
            ReportFileSummary(path=item.path, line_count=len(item.content.splitlines()))
            for item in workflow.generated_files
        ]

        is_partial = workflow.state == WorkflowState.FAILED
        failure = self._failure_info(workflow) if is_partial else None
        sections = self._section_statuses(workflow)

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
            duration_ms=duration_ms,
            generated_at=datetime.now(timezone.utc),
            report_status="partial" if is_partial else "complete",
            failure=failure,
            sections=sections,
            requirement=ReportRequirementSection(
                jira_task=workflow.jira_task,
                requirement_analysis=workflow.requirement_analysis,
                scope_analysis=workflow.scope_analysis,
                repository_analysis=workflow.repository_analysis,
                branch_analysis=workflow.branch_analysis,
            ),
            planning=ReportPlanningSection(
                complexity=workflow.complexity,
                model_recommendation=workflow.model_recommendation,
                model_selection=workflow.model_selection,
                selected_model=workflow.selected_model,
                plan=latest_plan,
            ),
            build=ReportBuildSection(
                base_branch=workflow.selected_base_branch,
                work_branch=workflow.work_branch or (workflow.implementation.branch if workflow.implementation else None),
                branch_collision=workflow.branch_analysis.branch_collision if workflow.branch_analysis else False,
                collision_message=workflow.branch_analysis.collision_message if workflow.branch_analysis else None,
                changed_files=workflow.implementation.changed_files if workflow.implementation else [item.path for item in workflow.generated_files],
                diff_summary=workflow.implementation.diff_summary if workflow.implementation else "",
                files=file_summaries,
            ),
            testing=ReportTestingSection(
                validation_status=workflow.implementation.validation_status if workflow.implementation else "UNKNOWN",
                validation_summary=workflow.implementation.validation_summary if workflow.implementation else "",
                test_result=workflow.test_result,
                terminal_log=workflow.terminal_log,
            ),
            delivery=ReportDeliverySection(
                pull_request=workflow.pull_request,
                pr_body=pr_body,
                jira_comment_posted=jira_comment_posted,
                jira_transition_posted=jira_transition_posted,
            ),
            audit_trail=workflow.mcp_audit,
        )

    def _failure_info(self, workflow: Workflow) -> ReportFailureInfo:
        stage = workflow.current_stage
        failed_agent = None
        for entry in reversed(workflow.audit_log):
            if entry.get("status") == "failed":
                failed_agent = entry.get("agent")
                break
        return ReportFailureInfo(
            stage=stage,
            stage_label=STAGE_LABELS.get(stage or "", stage),
            error=workflow.error,
            agent=failed_agent,
        )

    def _section_has_content(self, workflow: Workflow, section_id: str) -> bool:
        if section_id == "requirement":
            return workflow.jira_task is not None
        if section_id == "planning":
            return bool(workflow.plans or workflow.complexity or workflow.model_selection)
        if section_id == "build":
            return bool(workflow.generated_files or workflow.implementation)
        if section_id == "testing":
            return bool(workflow.terminal_log or workflow.test_result or workflow.implementation)
        if section_id == "delivery":
            return workflow.pull_request is not None
        return False

    def _section_statuses(self, workflow: Workflow) -> list[ReportSectionStatus]:
        is_failed = workflow.state == WorkflowState.FAILED
        failed_section = STAGE_TO_SECTION.get(workflow.current_stage or "")
        failed_index = next((index for index, (section_id, _) in enumerate(SECTION_DEFS) if section_id == failed_section), -1)

        statuses: list[ReportSectionStatus] = []
        for index, (section_id, label) in enumerate(SECTION_DEFS):
            if is_failed and section_id == failed_section:
                status = "failed"
            elif is_failed and failed_index >= 0 and index > failed_index:
                status = "not_reached"
            elif self._section_has_content(workflow, section_id):
                status = "completed"
            elif is_failed:
                status = "not_reached"
            else:
                status = "pending"
            statuses.append(ReportSectionStatus(id=section_id, label=label, status=status))
        return statuses
