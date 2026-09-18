from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

import httpx
from fastapi import HTTPException

from ..connection_models import GitConnectionConfig
from ..git_local import list_branches, normalize_work_branch
from ..models import PullRequest, RepositoryAnalysis


def repository_path(config: GitConnectionConfig) -> str:
    if not config.repository_path:
        raise HTTPException(status_code=400, detail="Repository path is required for direct Git mode.")
    path = Path(config.repository_path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Repository path must point to an accessible directory.")
    return str(path)


def validate_connection(config: GitConnectionConfig) -> str:
    path = repository_path(config)
    branches = list_branches(path)
    if not branches:
        raise HTTPException(status_code=400, detail="No git branches found. Ensure the path is a valid git repository.")
    return f"Repository ready with {len(branches)} branch(es)"


def analyze_repository(config: GitConnectionConfig, repository_path_value: str) -> RepositoryAnalysis:
    root = Path(repository_path_value)
    relevant_files: list[str] = []
    relevant_directories: list[str] = []
    for pattern in ("*.py", "*.ts", "*.tsx", "*.js", "*.go", "*.java"):
        for path in root.rglob(pattern):
            if any(part.startswith(".") or part in {"node_modules", ".venv", "venv", "__pycache__"} for part in path.parts):
                continue
            relative = str(path.relative_to(root)).replace("\\", "/")
            relevant_files.append(relative)
            parent = str(path.parent.relative_to(root)).replace("\\", "/")
            if parent not in relevant_directories and parent != ".":
                relevant_directories.append(parent)
            if len(relevant_files) >= 40:
                break
        if len(relevant_files) >= 40:
            break

    project_type = "Git repository"
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        project_type = "Python"
    elif (root / "package.json").exists():
        project_type = "Node.js"

    test_command = "pytest" if project_type == "Python" else None
    return RepositoryAnalysis(
        project_type=project_type,
        relevant_directories=relevant_directories[:10] or ["."],
        relevant_files=relevant_files[:20],
        test_command=test_command,
        notes="Repository analyzed locally (direct Git mode).",
    )


def _run_git(path: str, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "git command failed").strip()
        raise HTTPException(status_code=502, detail=f"Git command failed: {detail}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Git is not installed or not available on PATH.") from exc


def create_branch(
    config: GitConnectionConfig,
    repository_path_value: str,
    jira_key: str,
    summary: str,
    *,
    base_branch: str | None = None,
    branch_name: str | None = None,
) -> str:
    path = repository_path_value
    target = branch_name or normalize_work_branch(jira_key, summary)
    if target in list_branches(path):
        _run_git(path, "checkout", target)
        logger.info("git_branch_reused repository=%s branch=%s", path, target)
        return target
    base = base_branch or config.base_branch or "main"
    _run_git(path, "fetch", config.remote, base)
    _run_git(path, "checkout", base)
    _run_git(path, "pull", config.remote, base)
    _run_git(path, "checkout", "-b", target)
    logger.info("git_branch_created repository=%s branch=%s base=%s", path, target, base)
    return target


def write_files(repository_path_value: str, files: list[dict[str, str]]) -> list[str]:
    root = Path(repository_path_value)
    changed: list[str] = []
    for item in files:
        relative = item.get("path")
        if not relative:
            continue
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(item.get("content", ""), encoding="utf-8")
        changed.append(relative.replace("\\", "/"))
    if changed:
        _run_git(str(root), "add", *changed)
        _run_git(str(root), "commit", "-m", f"aidlc: update {len(changed)} file(s)")
    return changed


def push_branch(config: GitConnectionConfig, repository_path_value: str, branch_name: str) -> None:
    _run_git(repository_path_value, "push", "-u", config.remote, branch_name)


async def create_pull_request(
    config: GitConnectionConfig,
    repository_path_value: str,
    *,
    title: str,
    body: str,
    base_branch: str,
    head_branch: str,
) -> PullRequest:
    path = Path(repository_path_value)
    origin = _run_git(str(path), "remote", "get-url", config.remote).stdout.strip()
    if origin.startswith("git@"):
        repo_path = origin.split(":")[-1].removesuffix(".git")
        owner_repo = repo_path
    elif "github.com" in origin:
        owner_repo = "/".join(origin.rstrip("/").split("/")[-2:]).removesuffix(".git")
    else:
        return PullRequest(number=0, title=title, url=f"file://{path}", status="LOCAL")

    token = config.mcp_token or os.environ.get("GITHUB_TOKEN")
    if not token:
        return PullRequest(number=0, title=title, url=f"https://github.com/{owner_repo}/compare/{base_branch}...{head_branch}", status="DRAFT")

    url = f"https://api.github.com/repos/{owner_repo}/pulls"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"title": title, "body": body, "head": head_branch, "base": base_branch},
        )
    if response.status_code >= 400:
        payload = response.text[:240]
        raise HTTPException(status_code=502, detail=f"GitHub PR creation failed: HTTP {response.status_code} {payload}")
    data = response.json()
    return PullRequest(number=int(data.get("number") or 0), title=str(data.get("title") or title), url=str(data.get("html_url") or ""), status="OPEN")
