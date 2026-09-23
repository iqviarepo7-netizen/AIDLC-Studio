import asyncio
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
from .config_loader import load_app_config
from .connection_models import BranchPreviewRequest, ConnectionCheckResult, GitConnectionConfig, JiraConnectionConfig, SessionConnection, SetupRequest, SetupResponse, SetupSummary
from .git_local import list_branches, resolve_base_branch
from .models import ApproveWorkflowRequest, CreateWorkflowRequest, ModelSelectionRequest, WorkflowState
from .session_context import set_current_session
from .session_store import SessionStore
from .setup_service import validate_git, validate_jira
from .store import WorkflowStore
from .jira_create_models import CreateJiraAgentRequest, CreateJiraIssueRequest, CreateJiraMetadataRequest
from .jira_create_service import create_issue, get_create_metadata, list_issue_types, list_projects, run_create_jira_agent
from .workflow import Orchestrator

log_directory = Path(__file__).resolve().parents[1] / "logs"
log_directory.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(log_directory / "aidlc.log", encoding="utf-8")],
    force=True,
)

settings = get_settings()
_env_map = {
    "GEMINI_MODEL_LOW": settings.gemini_model_low,
    "GEMINI_MODEL_MEDIUM": settings.gemini_model_medium,
    "GEMINI_MODEL_HIGH": settings.gemini_model_high,
    "GROQ_MODEL_LOW": settings.groq_model_low,
    "GROQ_MODEL_MEDIUM": settings.groq_model_medium,
    "GROQ_MODEL_HIGH": settings.groq_model_high,
    "JIRA_MCP_URL": settings.jira_mcp_url,
    "JIRA_MCP_TOKEN": settings.jira_mcp_token,
    "GIT_MCP_URL": settings.git_mcp_url,
    "GIT_MCP_TOKEN": settings.git_mcp_token,
    "JIRA_DONE_TRANSITION_ID": settings.jira_done_transition_id,
    "WORKFLOW_STORE_PATH": settings.workflow_store_path,
    "GITHUB_BASE_BRANCH": settings.github_base_branch,
}
for key, value in _env_map.items():
    if value:
        os.environ[key] = value

config = load_app_config()
store_path = settings.workflow_store_path or config.policy.workflow.store_path
store = WorkflowStore(store_path)
session_store = SessionStore()
orchestrator = Orchestrator(store, settings, config)

app = FastAPI(title="AIDLC Studio API", version="0.3.0")
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = request.headers.get("X-Session-Id")
        set_current_session(session_store.get(session_id))
        try:
            return await call_next(request)
        finally:
            set_current_session(None)


app.add_middleware(SessionMiddleware)


def optional_session(request: Request) -> SessionConnection | None:
    return session_store.get(request.headers.get("X-Session-Id"))


def require_session(request: Request) -> SessionConnection:
    session = optional_session(request)
    if session:
        return session
    if settings.repository_path and (settings.jira_mcp_url or settings.git_mcp_url):
        return SessionConnection(
            jira=JiraConnectionConfig(
                mode="mcp",
                mcp_url=settings.jira_mcp_url,
                mcp_token=settings.jira_mcp_token,
                transition_id=settings.jira_done_transition_id,
            ),
            git=GitConnectionConfig(
                mode="mcp",
                mcp_url=settings.git_mcp_url,
                mcp_token=settings.git_mcp_token,
                repository_path=settings.repository_path,
                base_branch=settings.github_base_branch,
            ),
        )
    raise HTTPException(status_code=401, detail="Complete setup before using the studio.")


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    session = optional_session(request)
    return {
        "status": "ok",
        "automation_mode": config.policy.automation.mode,
        "mcp": {
            "jira_configured": bool(session.jira.mcp_url if session and session.jira.mode == "mcp" else settings.jira_mcp_url),
            "git_configured": bool(session.git.mcp_url if session and session.git.mode == "mcp" else settings.git_mcp_url),
        },
        "repository_configured": bool(session.git.repository_path if session else settings.repository_path),
        "gemini_configured": bool(settings.gemini_api_key),
        "groq_configured": bool(settings.groq_api_key),
        "session_active": bool(session),
    }


@app.get("/api/config/public")
def public_config() -> dict[str, object]:
    payload = config.public_ui_config()
    payload["require_setup"] = not bool(settings.repository_path and settings.jira_mcp_url)
    return payload


@app.post("/api/setup/branches")
def preview_setup_branches(request: BranchPreviewRequest) -> dict[str, object]:
    path = Path(request.repository_path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Repository path must point to an accessible directory.")
    branches = list_branches(str(path))
    if not branches:
        raise HTTPException(status_code=400, detail="No git branches found. Ensure the path is a valid git repository.")
    default_branch = resolve_base_branch(None, branches, settings.github_base_branch)
    logging.getLogger(__name__).info("setup_branches_preview path=%s count=%s default=%s", path, len(branches), default_branch)
    return {"branches": branches, "default_branch": default_branch}


@app.post("/api/setup/validate")
async def validate_setup(request: SetupRequest) -> SetupResponse:
    jira_message = await validate_jira(request.jira)
    git_message = await validate_git(request.git)
    branches: list[str] = []
    default_branch = request.git.base_branch or settings.github_base_branch or "main"
    if request.git.mode == "direct" and request.git.repository_path:
        from .integrations import direct_git

        branches = list_branches(direct_git.repository_path(request.git))
        default_branch = resolve_base_branch(request.git.base_branch, branches, settings.github_base_branch)

    session = session_store.create(SessionConnection(jira=request.jira, git=request.git))
    return SetupResponse(
        session_id=session.session_id,
        jira=ConnectionCheckResult(ok=True, mode=request.jira.mode, message=jira_message),
        git=ConnectionCheckResult(ok=True, mode=request.git.mode, message=git_message),
        branches=branches,
        default_branch=default_branch,
        summary=session.public_summary(),
    )


@app.get("/api/setup/session")
def get_setup_session(session: SessionConnection = Depends(require_session)) -> dict[str, SetupSummary]:
    return {"summary": session.public_summary()}


@app.get("/api/setup/session/config")
def get_setup_session_config(session: SessionConnection = Depends(require_session)) -> SetupRequest:
    return SetupRequest(jira=session.jira, git=session.git)


@app.get("/api/repository/branches")
def list_repository_branches(session: SessionConnection = Depends(require_session)) -> dict[str, object]:
    repository_path = session.git.repository_path or settings.repository_path
    if not repository_path:
        raise HTTPException(status_code=503, detail="Repository path is not configured.")
    branches = list_branches(str(Path(repository_path).expanduser().resolve()))
    default_branch = resolve_base_branch(session.git.base_branch, branches, settings.github_base_branch)
    return {"branches": branches, "default_branch": default_branch}


@app.get("/api/jira/create/projects")
async def jira_create_projects(session: SessionConnection = Depends(require_session)):
    from .jira_create_service import require_direct_jira

    config = require_direct_jira(session)
    return {"projects": [item.model_dump() for item in await list_projects(config)]}


@app.get("/api/jira/create/issue-types")
async def jira_create_issue_types(project_id: str, session: SessionConnection = Depends(require_session)):
    from .jira_create_service import require_direct_jira

    config = require_direct_jira(session)
    return {"issue_types": [item.model_dump() for item in await list_issue_types(config, project_id)]}


@app.post("/api/jira/create/metadata")
async def jira_create_metadata(request: CreateJiraMetadataRequest, session: SessionConnection = Depends(require_session)):
    return await get_create_metadata(session, request)


@app.post("/api/jira/create/issue")
async def jira_create_issue(request: CreateJiraIssueRequest, session: SessionConnection = Depends(require_session)):
    result = await create_issue(session, request)
    logging.getLogger(__name__).info("jira_issue_created key=%s project=%s issue_type=%s", result.key, request.project_id, request.issue_type_id)
    return result


@app.post("/api/jira/create/agent")
async def jira_create_agent(request: CreateJiraAgentRequest, session: SessionConnection = Depends(require_session)):
    return await run_create_jira_agent(session, settings, request)


@app.post("/api/workflows")
async def create_workflow(request: CreateWorkflowRequest, session: SessionConnection = Depends(require_session)):
    set_current_session(session)
    workflow = orchestrator.create(request.jira_key, request.base_branch or session.git.base_branch)
    workflow = await orchestrator.load_jira_task(workflow)
    if config.policy.automation.auto_start:
        return await orchestrator.run(workflow.id)
    return workflow


@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, session: SessionConnection = Depends(require_session)):
    set_current_session(session)
    return await orchestrator.run(workflow_id)


@app.post("/api/workflows/{workflow_id}/model-selection")
async def select_workflow_model(workflow_id: str, request: ModelSelectionRequest, session: SessionConnection = Depends(require_session)):
    set_current_session(session)
    return await orchestrator.select_model(workflow_id, request.route_id, request.work_branch)


@app.post("/api/workflows/{workflow_id}/proceed-plan")
async def proceed_workflow_plan(workflow_id: str, session: SessionConnection = Depends(require_session)):
    set_current_session(session)
    return await orchestrator.proceed_plan(workflow_id)


@app.post("/api/workflows/{workflow_id}/regenerate-plan")
async def regenerate_workflow_plan(workflow_id: str, session: SessionConnection = Depends(require_session)):
    set_current_session(session)
    return await orchestrator.regenerate_plan(workflow_id)


@app.get("/api/workflows/{workflow_id}/events")
async def workflow_events(workflow_id: str):
    terminal = {WorkflowState.COMPLETED, WorkflowState.FAILED}

    async def stream():
        last_revision: str | None = None
        while True:
            workflow = store.get(workflow_id)
            revision = f"{workflow.updated_at.isoformat()}:{workflow.state}:{workflow.current_stage}:{len(workflow.generated_files)}:{len(workflow.terminal_log)}"
            if revision != last_revision:
                last_revision = revision
                yield f"data: {workflow.model_dump_json()}\n\n"
            if workflow.state in terminal:
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@app.post("/api/workflows/{workflow_id}/approve")
async def approve_workflow(workflow_id: str, request: ApproveWorkflowRequest, session: SessionConnection = Depends(require_session)):
    if not request.approved:
        raise HTTPException(status_code=400, detail="Only approval is supported in review_required mode.")
    set_current_session(session)
    return await orchestrator.approve(workflow_id)


@app.post("/api/workflows/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, session: SessionConnection = Depends(require_session)):
    set_current_session(session)
    logging.getLogger(__name__).info("api_resume workflow_id=%s session=%s", workflow_id, session.session_id)
    return await orchestrator.resume(workflow_id)


@app.get("/api/workflows/{workflow_id}/jira-sync")
async def jira_sync_workflow(workflow_id: str, session: SessionConnection = Depends(require_session)):
    set_current_session(session)
    return await orchestrator.check_jira_sync(workflow_id)


@app.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    return store.get(workflow_id)


@app.get("/api/workflows/{workflow_id}/files/{file_path:path}")
def get_workflow_file(workflow_id: str, file_path: str):
    workflow = store.get(workflow_id)
    for item in workflow.generated_files:
        if item.path == file_path:
            return PlainTextResponse(item.content)
    raise HTTPException(status_code=404, detail="File not found in workflow artifacts.")


@app.get("/api/workflows/{workflow_id}/report")
def report(workflow_id: str):
    from .agents.report import ReportAgent

    workflow = store.get(workflow_id)
    if workflow.state == WorkflowState.COMPLETED:
        payload = workflow.report or ReportAgent().generate(workflow)
        return {"status": "complete", "workflow": workflow, "report": payload}
    if workflow.state == WorkflowState.FAILED:
        payload = workflow.report or ReportAgent().generate(workflow)
        return {"status": "partial", "workflow": workflow, "report": payload}
    return {"status": "incomplete", "workflow": workflow}
