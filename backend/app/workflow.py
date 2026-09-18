from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from .agents import (
    ComplexityAgent,
    ImplementationAgent,
    ModelSelectorAgent,
    PlanningAgent,
    PublisherAgent,
    ReportAgent,
    ScopeAnalyzerAgent,
    TaskAnalyzerAgent,
    ValidatorAgent,
)
from .config import Settings, get_settings
from .config_loader import AppConfig, load_app_config
from .git_local import list_branches, resolve_base_branch, suggest_work_branch
from .llm import ModelGateway
from .mcp.adapter import MCPAdapter
from .session_context import get_current_session
from .models import (
    BranchAnalysis,
    GeneratedFileRecord,
    ImplementationResult,
    TestResult,
    Workflow,
    WorkflowState,
)
from .store import WorkflowStore
from .terminal_runner import TerminalRunner

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        store: WorkflowStore,
        settings: Settings | None = None,
        config: AppConfig | None = None,
        mcp: MCPAdapter | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.config = config or load_app_config()
        self.mcp = mcp or MCPAdapter(self.config)
        self.gateway = ModelGateway(self.settings)
        self.terminal = TerminalRunner(self.config)
        self.task_analyzer = TaskAnalyzerAgent(self.config)
        self.scope_analyzer = ScopeAnalyzerAgent()
        self.complexity = ComplexityAgent(self.config)
        self.model_selector = ModelSelectorAgent(self.config)
        self.planning = PlanningAgent(self.config)
        self.validator = ValidatorAgent(self.config, self.terminal)
        self.publisher = PublisherAgent(self.config, self.mcp)
        self.report_agent = ReportAgent()

    def create(self, jira_key: str, base_branch: str | None = None) -> Workflow:
        workflow = Workflow(jira_key=jira_key.upper())
        if base_branch:
            workflow.selected_base_branch = base_branch.strip()
        return self.store.create(workflow)

    def list_repository_branches(self) -> list[str]:
        return list_branches(self._repository_path())

    async def run(self, workflow_id: str) -> Workflow:
        workflow = self.store.get(workflow_id)
        repository_path = self._repository_path()
        try:
            workflow = await self._analyze(workflow, repository_path)
            if workflow.state == WorkflowState.MODEL_RECOMMENDED:
                return workflow
            return await self._build_and_publish(workflow, repository_path)
        except HTTPException as exc:
            workflow.state = WorkflowState.FAILED
            workflow.error = str(exc.detail)
            self._audit(workflow, "orchestrator", "failed")
            return self.store.save(workflow)

    async def select_model(self, workflow_id: str, route_id: str, work_branch: str | None = None) -> Workflow:
        workflow = self.store.get(workflow_id)
        if workflow.state != WorkflowState.MODEL_RECOMMENDED:
            raise HTTPException(status_code=409, detail="Workflow is not awaiting model selection.")
        try:
            workflow.model_selection = self.model_selector.selection_for_route(route_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        workflow.selected_model = route_id
        if work_branch:
            workflow.work_branch = work_branch.strip()
            if workflow.branch_analysis:
                workflow.branch_analysis.suggested_work_branch = workflow.work_branch
        self._audit(workflow, "model_selector", "user_selected")
        return await self._build_and_publish(workflow, self._repository_path())

    async def proceed_plan(self, workflow_id: str) -> Workflow:
        workflow = self.store.get(workflow_id)
        if workflow.current_stage != "plan_review" or not workflow.plans:
            raise HTTPException(status_code=409, detail="Workflow is not awaiting plan approval.")
        workflow.current_stage = "implement"
        self.store.save(workflow)
        return await self._continue_build(workflow, self._repository_path())

    async def regenerate_plan(self, workflow_id: str) -> Workflow:
        workflow = self.store.get(workflow_id)
        if workflow.current_stage != "plan_review":
            raise HTTPException(status_code=409, detail="Workflow is not awaiting plan approval.")
        return await self._generate_plan(workflow, self._repository_path(), replace=True)

    async def _analyze(self, workflow: Workflow, repository_path: str) -> Workflow:
        workflow.state = WorkflowState.RUNNING if workflow.retry_count == 0 else WorkflowState.RETRYING
        workflow.error = None
        self._set_stage(workflow, "fetch_issue")
        workflow.state = WorkflowState.ANALYZING
        self.store.save(workflow)
        workflow.jira_task = await self.mcp.fetch_issue(workflow, workflow.jira_key)
        workflow.requirement_analysis = self.task_analyzer.analyze(workflow.jira_task)
        workflow.repository_analysis = await self.mcp.analyze_repository(workflow, repository_path)
        workflow.scope_analysis = self.scope_analyzer.analyze(workflow.jira_task, workflow.repository_analysis)
        self.store.save(workflow)
        branches = list_branches(repository_path)
        base_branch = resolve_base_branch(
            workflow.selected_base_branch,
            branches,
            (session.git.base_branch if (session := get_current_session()) and session.git.base_branch else None)
            or self.settings.github_base_branch,
        )
        workflow.selected_base_branch = base_branch
        branch_suggestion = suggest_work_branch(workflow.jira_key, workflow.jira_task.summary, branches)
        workflow.branch_analysis = BranchAnalysis(
            base_branch=base_branch,
            suggested_work_branch=branch_suggestion.suggested_work_branch,
            existing_branches=branch_suggestion.existing_branches,
            branch_collision=branch_suggestion.branch_collision,
            collision_message=branch_suggestion.collision_message,
        )
        workflow.work_branch = branch_suggestion.suggested_work_branch
        self._audit(workflow, "scope_analyzer", "completed")
        return await self._finish_analysis(workflow)

    async def _finish_analysis(self, workflow: Workflow) -> Workflow:
        if not workflow.jira_task or not workflow.repository_analysis:
            raise HTTPException(status_code=409, detail="Issue analysis is incomplete.")
        first_route = self.config.policy.model_routing[0] if self.config.policy.model_routing else None
        assessment_provider = (
            self.gateway.provider(first_route.provider, first_route.model, first_route.max_tokens) if first_route else None
        )
        workflow.complexity = await self.complexity.assess(workflow.jira_task, workflow.repository_analysis, assessment_provider)
        workflow.model_recommendation = self.model_selector.recommend(workflow.complexity)
        self._audit(workflow, "complexity", "completed")
        if self._require_model_selection():
            workflow.state = WorkflowState.MODEL_RECOMMENDED
            return self.store.save(workflow)
        workflow.model_selection = self.model_selector.select(workflow.complexity, workflow.retry_count)
        workflow.selected_model = workflow.model_recommendation.recommended_model_id if workflow.model_recommendation else f"{workflow.model_selection.provider}:{workflow.model_selection.model}"
        self._audit(workflow, "model_selector", "auto_selected")
        return self.store.save(workflow)

    async def _build_and_publish(self, workflow: Workflow, repository_path: str) -> Workflow:
        workflow = await self._ensure_plan(workflow, repository_path)
        if workflow.current_stage == "plan_review":
            return workflow
        return await self._continue_build(workflow, repository_path)

    async def _ensure_plan(self, workflow: Workflow, repository_path: str) -> Workflow:
        if workflow.current_stage == "plan_review" and workflow.plans:
            return workflow
        if workflow.plans and workflow.current_stage not in {None, "plan", "plan_review"}:
            return workflow
        return await self._generate_plan(workflow, repository_path, replace=False)

    async def _generate_plan(self, workflow: Workflow, repository_path: str, *, replace: bool) -> Workflow:
        del repository_path
        if not workflow.jira_task or not workflow.repository_analysis or not workflow.model_selection:
            raise HTTPException(status_code=409, detail="Analysis and model selection are required before planning.")
        workflow.state = WorkflowState.PLANNING
        self._set_stage(workflow, "plan")
        self.store.save(workflow)
        plan = await self.planning.plan(
            workflow.jira_task,
            workflow.repository_analysis,
            len(workflow.plans) + (0 if replace else 1),
            workflow.scope_analysis,
            self.gateway.provider(
                workflow.model_selection.provider,
                workflow.model_selection.model,
                workflow.model_selection.max_tokens,
            ),
        )
        workflow.plans = [plan]
        self._set_stage(workflow, "plan_review")
        self._audit(workflow, "planner", "regenerated" if replace else "completed")
        return self.store.save(workflow)

    async def _continue_build(self, workflow: Workflow, repository_path: str) -> Workflow:
        max_retries = self.config.policy.automation.max_retries
        while workflow.retry_count <= max_retries:
            try:
                if workflow.retry_count:
                    workflow.model_selection = self.model_selector.route_for_retry(workflow.model_selection, workflow.retry_count)
                    workflow.selected_model = f"{workflow.model_selection.provider}:{workflow.model_selection.model}"

                workflow.state = WorkflowState.IMPLEMENTING
                self._set_stage(workflow, "implement")
                self.store.save(workflow)
                base_branch = workflow.selected_base_branch or workflow.branch_analysis.base_branch if workflow.branch_analysis else "main"
                work_branch = workflow.work_branch or (
                    workflow.branch_analysis.suggested_work_branch if workflow.branch_analysis else None
                )
                branch = await self.mcp.create_branch(
                    workflow,
                    repository_path,
                    workflow.jira_task.key,
                    workflow.jira_task.summary,
                    base_branch=base_branch,
                    branch_name=work_branch,
                )
                plan = workflow.plans[0]
                provider = self.gateway.provider(
                    workflow.model_selection.provider,
                    workflow.model_selection.model,
                    workflow.model_selection.max_tokens,
                )
                implementation_agent = ImplementationAgent(self.config, provider)
                generated, summary = await implementation_agent.generate(workflow.jira_task, plan, workflow.repository_analysis)
                workflow.generated_files = [GeneratedFileRecord(path=item.path, content=item.content) for item in generated]
                self.store.save(workflow)
                changed_files = await self.mcp.write_files(
                    workflow,
                    repository_path,
                    [{"path": item.path, "content": item.content} for item in generated],
                )

                workflow.state = WorkflowState.VALIDATING
                self._set_stage(workflow, "validate")
                self.store.save(workflow)
                passed, validation_summary = self.validator.validate(workflow, repository_path)
                status, passed_count, failed_count, command, test_summary = self.terminal.summarize(workflow.terminal_log)
                workflow.test_result = TestResult(
                    generated_tests=[path for path in changed_files if "test" in path.lower()],
                    executed_command=command,
                    passed=passed_count,
                    failed=failed_count,
                    status=status,
                    summary=test_summary,
                )
                workflow.implementation = ImplementationResult(
                    branch=branch,
                    changed_files=changed_files,
                    diff_summary=summary,
                    validation_status="PASS" if passed else "FAIL",
                    validation_summary=validation_summary,
                )
                workflow.work_branch = branch

                if not passed:
                    if workflow.retry_count < max_retries and "validation_fail" in self.config.policy.automation.retry_on:
                        workflow.retry_count += 1
                        self._audit(workflow, "validator", "retry")
                        self.store.save(workflow)
                        continue
                    workflow.state = WorkflowState.FAILED
                    workflow.error = "Validation failed and retry limit was reached."
                    return self.store.save(workflow)

                if self.config.policy.automation.mode == "review_required":
                    workflow.state = WorkflowState.AWAITING_REVIEW
                    self._audit(workflow, "orchestrator", "awaiting_review")
                    return self.store.save(workflow)

                return await self._publish(workflow, repository_path)

            except HTTPException as exc:
                workflow.state = WorkflowState.FAILED
                workflow.error = str(exc.detail)
                self._audit(workflow, "orchestrator", "failed")
                return self.store.save(workflow)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.exception("workflow_failed workflow_id=%s", workflow.id)
                workflow.state = WorkflowState.FAILED
                workflow.error = str(exc)
                return self.store.save(workflow)

        workflow.state = WorkflowState.FAILED
        workflow.error = "Retry limit reached."
        return self.store.save(workflow)

    async def approve(self, workflow_id: str) -> Workflow:
        workflow = self.store.get(workflow_id)
        if workflow.state != WorkflowState.AWAITING_REVIEW:
            raise HTTPException(status_code=409, detail="Workflow is not awaiting review.")
        return await self._publish(workflow, self._repository_path())

    async def resume(self, workflow_id: str) -> Workflow:
        workflow = self.store.get(workflow_id)
        repository_path = self._repository_path()
        if workflow.state == WorkflowState.AWAITING_REVIEW:
            logger.info("workflow_resume workflow_id=%s action=publish", workflow_id)
            return await self._publish(workflow, repository_path)
        if workflow.state != WorkflowState.FAILED:
            raise HTTPException(status_code=409, detail="Only failed workflows can be resumed from the last checkpoint.")
        logger.info(
            "workflow_resume workflow_id=%s jira_key=%s stage=%s model_selected=%s",
            workflow.id,
            workflow.jira_key,
            workflow.current_stage,
            bool(workflow.model_selection),
        )
        workflow.error = None
        self._audit(workflow, "orchestrator", "resume")
        try:
            if workflow.model_selection:
                return await self._build_and_publish(workflow, repository_path)
            if workflow.complexity and self._require_model_selection():
                workflow.state = WorkflowState.MODEL_RECOMMENDED
                return self.store.save(workflow)
            if workflow.scope_analysis and workflow.jira_task and workflow.repository_analysis:
                return await self._finish_analysis(workflow)
            return await self._analyze(workflow, repository_path)
        except HTTPException as exc:
            workflow.state = WorkflowState.FAILED
            workflow.error = str(exc.detail)
            self._audit(workflow, "orchestrator", "failed")
            return self.store.save(workflow)

    async def check_jira_sync(self, workflow_id: str) -> dict[str, object]:
        from .integrations import direct_jira

        workflow = self.store.get(workflow_id)
        if workflow.state != WorkflowState.COMPLETED or not workflow.pull_request:
            raise HTTPException(status_code=409, detail="Workflow must be completed with a pull request before Jira sync check.")
        session = get_current_session()
        if not session or session.jira.mode != "direct":
            raise HTTPException(status_code=503, detail="Jira sync check requires direct Jira mode in the active session.")
        found = await direct_jira.has_pr_comment(session.jira, workflow.jira_key, workflow.pull_request.url)
        logger.info(
            "jira_sync_check workflow_id=%s jira_key=%s found=%s pr_url=%s",
            workflow.id,
            workflow.jira_key,
            found,
            workflow.pull_request.url,
        )
        self._audit(workflow, "orchestrator", "jira_sync_ok" if found else "jira_sync_pending")
        return {
            "jira_comment_found": found,
            "pr_url": workflow.pull_request.url,
            "jira_key": workflow.jira_key,
            "flow_complete": found,
        }

    async def _publish(self, workflow: Workflow, repository_path: str) -> Workflow:
        workflow.state = WorkflowState.PUBLISHING
        self._set_stage(workflow, "publish")
        self.store.save(workflow)
        workflow.pull_request = await self.publisher.publish(workflow, repository_path)
        workflow.report = self.report_agent.generate(workflow)
        workflow.state = WorkflowState.COMPLETED
        self._audit(workflow, "publisher", "completed")
        return self.store.save(workflow)

    def _require_model_selection(self) -> bool:
        return self.config.policy.automation.require_model_selection

    def _repository_path(self) -> str:
        session = get_current_session()
        configured_path = session.git.repository_path if session and session.git.repository_path else self.settings.repository_path
        if not configured_path:
            raise HTTPException(status_code=503, detail="Repository path is not configured.")
        path = Path(configured_path).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(status_code=503, detail="Repository path must point to an accessible directory.")
        return str(path)

    def _set_stage(self, workflow: Workflow, stage: str) -> None:
        workflow.current_stage = stage

    @staticmethod
    def _audit(workflow: Workflow, agent: str, status: str) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "action": workflow.current_stage or "pipeline",
            "status": status,
        }
        workflow.audit_log.append(event)
        logger.info(
            "workflow_event workflow_id=%s jira_key=%s agent=%s status=%s",
            workflow.id,
            workflow.jira_key,
            agent,
            status,
        )
