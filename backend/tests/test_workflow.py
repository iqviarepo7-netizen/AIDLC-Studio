import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from app.config_loader import load_app_config
from app.guardrails import Guardrails, GuardrailViolation
from app.models import ComplexityAssessment, JiraTask, Workflow, WorkflowState
from app.store import WorkflowStore
from app.workflow import Orchestrator
from app.mcp.adapter import MCPAdapter
from app.agents.implementation import ImplementationAgent


@pytest.fixture
def tmp_store(tmp_path: Path) -> WorkflowStore:
    return WorkflowStore(tmp_path / "workflows.json")


@pytest.fixture
def mock_mcp() -> AsyncMock:
    mcp = AsyncMock(spec=MCPAdapter)
    mcp.fetch_issue.return_value = JiraTask(key="DEMO-21", summary="Add health endpoint", description="Return ok status")
    mcp.analyze_repository.return_value = __import__("app.models", fromlist=["RepositoryAnalysis"]).RepositoryAnalysis(
        project_type="Python",
        relevant_directories=["."],
        relevant_files=["app/main.py"],
        test_command="pytest",
        notes="mock",
    )
    mcp.create_branch.return_value = "ai/demo-21-add-health-endpoint"
    mcp.write_files.return_value = ["app/main.py", "tests/test_main.py"]
    mcp.push_branch.return_value = None
    mcp.create_pull_request.return_value = __import__("app.models", fromlist=["PullRequest"]).PullRequest(
        number=1, title="Add health endpoint", url="https://example.com/pr/1", status="OPEN"
    )
    mcp.transition_issue.return_value = None
    mcp.comment_issue.return_value = None
    return mcp


def test_workflow_starts_new(tmp_store: WorkflowStore) -> None:
    orchestrator = Orchestrator(tmp_store, mcp=AsyncMock(spec=MCPAdapter))
    workflow = orchestrator.create("DEMO-21")
    assert workflow.jira_key == "DEMO-21"
    assert workflow.state == WorkflowState.NEW


def test_workflow_store_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "workflows.json"
    store = WorkflowStore(path)
    workflow = store.create(Workflow(jira_key="DEMO-22"))
    restored = WorkflowStore(path).get(workflow.id)
    assert restored.jira_key == "DEMO-22"


def test_implementation_response_parses_json() -> None:
    response = ImplementationAgent._parse('{"summary":"Added endpoint", "files":[{"path":"app/main.py", "content":"print(1)"}]}')
    assert response["summary"] == "Added endpoint"


def test_guardrail_blocks_unsafe_path() -> None:
    config = load_app_config()
    guardrails = Guardrails(config.policy.guardrails)
    with pytest.raises(GuardrailViolation):
        guardrails.validate_request("implementing", "git.write", {"files": [{"path": "../secret.env", "content": "x"}]})


def test_model_selector_uses_config_routes() -> None:
    from app.agents.model_selector import ModelSelectorAgent

    selector = ModelSelectorAgent(load_app_config())
    selection = selector.select(ComplexityAssessment(score=2, level="LOW", explanation="test", estimated_files=1))
    assert selection.provider == "groq"
    assert selection.model


@pytest.mark.asyncio
async def test_orchestrator_run_happy_path(tmp_store: WorkflowStore, mock_mcp: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app").mkdir()
    (repo / "tests").mkdir()

    orchestrator = Orchestrator(tmp_store, mcp=mock_mcp)
    orchestrator.config.policy.automation.require_model_selection = False
    monkeypatch.setattr(orchestrator, "_repository_path", lambda: str(repo))

    async def fake_generate(self, task, plan, repository):
        from app.agents.implementation import GeneratedFile

        return [GeneratedFile(path="app/main.py", content="print('ok')")], "Added endpoint"

    monkeypatch.setattr("app.agents.implementation.ImplementationAgent.generate", fake_generate)

    def fake_validate(self, workflow, repository_path):
        workflow.terminal_log.extend([])
        return True, "Validation passed"

    monkeypatch.setattr("app.agents.validator.ValidatorAgent.validate", fake_validate)

    async def fake_assess(self, task, repository=None, provider=None):
        return ComplexityAssessment(score=2, level="LOW", explanation="test", estimated_files=1)

    monkeypatch.setattr("app.agents.complexity.ComplexityAgent.assess", fake_assess)

    workflow = orchestrator.create("DEMO-21")
    result = await orchestrator.run(workflow.id)
    if result.current_stage == "plan_review":
        result = await orchestrator.proceed_plan(workflow.id)
    assert result.state == WorkflowState.COMPLETED
    assert result.pull_request is not None
    assert result.scope_analysis is not None
    assert result.branch_analysis is not None
    assert result.selected_base_branch
    mock_mcp.create_branch.assert_awaited()
    branch_kwargs = mock_mcp.create_branch.await_args.kwargs
    assert branch_kwargs["base_branch"]
    mock_mcp.fetch_issue.assert_awaited_once()
