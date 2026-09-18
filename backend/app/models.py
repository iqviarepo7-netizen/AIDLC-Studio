from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowState(str, Enum):
    NEW = "NEW"
    RUNNING = "RUNNING"
    ANALYZING = "ANALYZING"
    MODEL_RECOMMENDED = "MODEL_RECOMMENDED"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    VALIDATING = "VALIDATING"
    RETRYING = "RETRYING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JiraTask(BaseModel):
    key: str
    summary: str
    description: str | None = None
    issue_type: str = "TASK"
    priority: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)


class RequirementAnalysis(BaseModel):
    problem_summary: str
    functional_requirement: str
    acceptance_criteria: list[str]
    constraints: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class ComplexityAssessment(BaseModel):
    score: int = Field(ge=1, le=10)
    level: str
    explanation: str
    estimated_files: int


class ModelSelection(BaseModel):
    provider: str
    model: str
    max_tokens: int
    reason: str


class ModelOption(BaseModel):
    id: str
    provider: str
    model: str
    label: str
    available: bool
    recommended: bool
    estimated_tokens: int


class ModelRecommendation(BaseModel):
    recommended_model_id: str
    alternatives: list[ModelOption]
    reason: str


class Plan(BaseModel):
    version: int
    objective: str
    affected_components: list[str]
    likely_files: list[str]
    implementation_steps: list[str]
    test_approach: list[str]
    risks: list[str]
    expected_result: str
    change_request: str | None = None


class RepositoryAnalysis(BaseModel):
    project_type: str
    relevant_directories: list[str]
    relevant_files: list[str]
    test_command: str | None = None
    notes: str


class ScopeAnalysis(BaseModel):
    change_type: str
    pattern_summary: str
    already_implemented: bool = False
    already_implemented_reason: str | None = None
    related_files: list[str] = Field(default_factory=list)


class BranchAnalysis(BaseModel):
    base_branch: str
    suggested_work_branch: str
    existing_branches: list[str] = Field(default_factory=list)
    branch_collision: bool = False
    collision_message: str | None = None


class GeneratedFileRecord(BaseModel):
    path: str
    content: str


class ImplementationResult(BaseModel):
    branch: str
    changed_files: list[str]
    diff_summary: str
    validation_status: str
    validation_summary: str
    commit: str | None = None


class TestResult(BaseModel):
    generated_tests: list[str]
    executed_command: str
    passed: int
    failed: int
    status: str
    summary: str


class PullRequest(BaseModel):
    number: int
    title: str
    url: str
    status: str


class MCPAuditRecord(BaseModel):
    timestamp: datetime
    workflow_id: str
    agent: str
    server: str
    tool: str
    status: str
    duration_ms: int
    request_redacted: dict[str, Any] = Field(default_factory=dict)
    response_redacted: dict[str, Any] = Field(default_factory=dict)
    guardrail_result: str | None = None


class TerminalLogEntry(BaseModel):
    command_id: str
    command: str
    status: str
    output: str
    duration_ms: int


class WorkflowReport(BaseModel):
    jira_key: str
    summary: str
    complexity_level: str
    complexity_score: int
    selected_model: str
    validation_status: str
    pr_url: str | None = None
    final_status: str
    retry_count: int = 0


class Workflow(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    jira_key: str
    state: WorkflowState = WorkflowState.NEW
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
    jira_task: JiraTask | None = None
    requirement_analysis: RequirementAnalysis | None = None
    complexity: ComplexityAssessment | None = None
    model_recommendation: ModelRecommendation | None = None
    model_selection: ModelSelection | None = None
    selected_model: str | None = None
    plans: list[Plan] = Field(default_factory=list)
    repository_analysis: RepositoryAnalysis | None = None
    scope_analysis: ScopeAnalysis | None = None
    branch_analysis: BranchAnalysis | None = None
    selected_base_branch: str | None = None
    work_branch: str | None = None
    generated_files: list[GeneratedFileRecord] = Field(default_factory=list)
    implementation: ImplementationResult | None = None
    test_result: TestResult | None = None
    pull_request: PullRequest | None = None
    terminal_log: list[TerminalLogEntry] = Field(default_factory=list)
    mcp_audit: list[MCPAuditRecord] = Field(default_factory=list)
    audit_log: list[dict[str, Any]] = Field(default_factory=list)
    retry_count: int = 0
    current_stage: str | None = None
    report: WorkflowReport | None = None


class CreateWorkflowRequest(BaseModel):
    jira_key: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_]*-\d+$")
    base_branch: str | None = Field(default=None, min_length=1, max_length=256)


class ApproveWorkflowRequest(BaseModel):
    approved: bool = True


class ModelSelectionRequest(BaseModel):
    route_id: str = Field(min_length=1, max_length=128)
    work_branch: str | None = Field(default=None, min_length=1, max_length=256)
