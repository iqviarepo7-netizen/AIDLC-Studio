from app.git_local import matching_branches, normalize_work_branch, resolve_base_branch, suggest_work_branch
from app.agents.scope_analyzer import ScopeAnalyzerAgent
from app.models import JiraTask, RepositoryAnalysis


def test_normalize_work_branch() -> None:
    assert normalize_work_branch("DEMO-21", "Add health endpoint") == "ai/demo-21-add-health-endpoint"


def test_suggest_work_branch_without_collision() -> None:
    suggestion = suggest_work_branch("DEMO-21", "Add health endpoint", ["main", "develop"])
    assert suggestion.branch_collision is False
    assert suggestion.suggested_work_branch == "ai/demo-21-add-health-endpoint"


def test_suggest_work_branch_with_collision() -> None:
    existing = "ai/demo-21-add-health-endpoint"
    suggestion = suggest_work_branch("DEMO-21", "Add health endpoint", ["main", existing])
    assert suggestion.branch_collision is True
    assert suggestion.suggested_work_branch == f"{existing}_v1"


def test_matching_branches() -> None:
    branches = ["main", "ai/demo-21-add-health-endpoint", "ai/demo-21-add-health-endpoint_v1"]
    assert matching_branches(branches, "DEMO-21") == [
        "ai/demo-21-add-health-endpoint",
        "ai/demo-21-add-health-endpoint_v1",
    ]


def test_resolve_base_branch_prefers_requested() -> None:
    assert resolve_base_branch("develop", ["main", "develop"], "main") == "develop"


def test_scope_analyzer_detects_existing_pattern() -> None:
    agent = ScopeAnalyzerAgent()
    task = JiraTask(key="DEMO-1", summary="Fix health endpoint bug", description="Update existing route")
    repository = RepositoryAnalysis(
        project_type="Python",
        relevant_directories=["app"],
        relevant_files=["app/routes/health.py"],
        notes="Existing route module found",
    )
    result = agent.analyze(task, repository)
    assert result.change_type == "EXTEND_EXISTING"
    assert result.already_implemented is False
