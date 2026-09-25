from __future__ import annotations

import os
import re
import subprocess
import urllib.parse
from pathlib import Path

import httpx

from .config import settings


class GitError(Exception):
    pass


def _repo_path(repository_path: str) -> Path:
    path = Path(repository_path).expanduser().resolve()
    if not path.is_dir():
        raise GitError(f"Repository path is not a directory: {repository_path}")
    if not (path / ".git").exists():
        raise GitError(f"Not a git repository: {path}")
    return path


def _noninteractive_git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    return env


def _run_git(path: str, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = _noninteractive_git_env()
    if extra_env:
        env.update(extra_env)
    try:
        return subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "git command failed").strip()
        raise GitError(detail) from exc
    except FileNotFoundError as exc:
        raise GitError("Git is not installed or not on PATH.") from exc


def list_branches(repository_path: str) -> list[str]:
    path = _repo_path(repository_path)
    result = _run_git(str(path), "branch", "-a", "--format=%(refname:short)")
    branches: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip().removeprefix("origin/").strip()
        if not name or name == "HEAD" or name.endswith("/HEAD"):
            continue
        if name not in branches:
            branches.append(name)
    return sorted(branches)


def normalize_work_branch(jira_key: str, summary: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", summary.lower()).strip("-")[:40]
    key = jira_key.lower()
    return f"ai/{key}-{slug}" if slug else f"ai/{key}"


def analyze_repository(repository_path: str) -> dict:
    root = _repo_path(repository_path)
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
    return {
        "project_type": project_type,
        "relevant_directories": relevant_directories[:10] or ["."],
        "relevant_files": relevant_files[:20],
        "test_command": test_command,
        "notes": "Repository analyzed via AIDLC Git MCP server.",
    }


def create_branch(
    repository_path: str,
    jira_key: str,
    summary: str,
    *,
    base_branch: str | None = None,
    branch_name: str | None = None,
    remote: str | None = None,
) -> dict:
    path = str(_repo_path(repository_path))
    remote_name = remote or settings.git_remote
    target = branch_name or normalize_work_branch(jira_key, summary)
    branches = list_branches(path)
    if target in branches:
        _run_git(path, "checkout", target)
        return {"branch": target, "reused": True}

    base = base_branch or settings.git_base_branch or "main"
    fetch_target = _authenticated_fetch_target(path, remote_name)
    _run_git(path, "fetch", fetch_target, base)
    _run_git(path, "checkout", base)
    if fetch_target == remote_name:
        _run_git(path, "pull", remote_name, base)
    else:
        _run_git(path, "pull", fetch_target, base)
    _run_git(path, "checkout", "-b", target)
    return {"branch": target, "reused": False}


def _commit_staged_if_needed(path: str, message: str) -> None:
    """Commit staged changes; no-op when content already matches HEAD (e.g. workflow retry)."""
    check = subprocess.run(
        ["git", "-C", path, "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check.returncode == 0:
        return
    _run_git(path, "commit", "-m", message)


def write_files(repository_path: str, files: list[dict]) -> dict:
    root = _repo_path(repository_path)
    changed: list[str] = []
    for item in files:
        relative = item.get("path")
        if not relative:
            continue
        destination = root / str(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(item.get("content", "")), encoding="utf-8")
        changed.append(str(relative).replace("\\", "/"))
    if changed:
        path = str(root)
        _run_git(path, "add", *changed)
        _commit_staged_if_needed(path, f"aidlc: update {len(changed)} file(s)")
    return {"changed_files": changed}


def current_branch(repository_path: str) -> str:
    path = str(_repo_path(repository_path))
    result = _run_git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip()


def push_branch(
    repository_path: str,
    *,
    branch_name: str | None = None,
    remote: str | None = None,
    github_token: str | None = None,
    gitlab_token: str | None = None,
) -> dict:
    path = str(_repo_path(repository_path))
    remote_name = remote or settings.git_remote
    branch = branch_name or current_branch(path)
    origin = _origin_url(path, remote_name)
    token, gitlab_base = _host_token_for_origin(origin, github_token=github_token, gitlab_token=gitlab_token)
    if not token:
        raise GitError(
            "Host token required for push (set GITHUB_TOKEN or GITLAB_TOKEN in mcp-servers/git/.env). "
            "Local Git Credential Manager is not used."
        )
    push_url = _authenticated_https_remote(origin, token, gitlab_base_url=gitlab_base)
    if not push_url:
        raise GitError(f"Unsupported remote for token-based push: {origin}")
    _run_git(path, "push", "-u", push_url, branch)
    return {"branch": branch, "remote": remote_name}


def _owner_repo_from_origin(origin: str) -> str | None:
    origin = origin.strip()
    if origin.startswith("git@"):
        return origin.split(":")[-1].removesuffix(".git")
    if origin.startswith("http://") or origin.startswith("https://"):
        parts = origin.rstrip("/").split("/")
        if len(parts) >= 2:
            return "/".join(parts[-2:]).removesuffix(".git")
    return None


def _resolve_github_token(override: str | None = None) -> str | None:
    return override or settings.github_token or os.environ.get("GITHUB_TOKEN")


def _resolve_gitlab_token(override: str | None = None) -> str | None:
    return override or settings.gitlab_token or os.environ.get("GITLAB_TOKEN")


def _gitlab_base_from_origin(origin: str, gitlab_base_url: str | None = None) -> str:
    if gitlab_base_url:
        return gitlab_base_url.rstrip("/")
    if origin.startswith("http://") or origin.startswith("https://"):
        parsed = urllib.parse.urlparse(origin)
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if origin.startswith("git@"):
        host = origin.split("@", 1)[1].split(":", 1)[0]
        return f"https://{host}"
    return (settings.gitlab_base_url or os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")).rstrip("/")


def _authenticated_https_remote(origin: str, token: str, *, gitlab_base_url: str | None = None) -> str | None:
    owner_repo = _owner_repo_from_origin(origin)
    if not owner_repo:
        return None
    encoded = urllib.parse.quote(token, safe="")
    origin_lower = origin.lower()
    if "gitlab" in origin_lower:
        base = _gitlab_base_from_origin(origin, gitlab_base_url)
        parsed = urllib.parse.urlparse(base if "://" in base else f"https://{base}")
        host = parsed.netloc or parsed.path
        scheme = parsed.scheme or "https"
        return f"{scheme}://oauth2:{encoded}@{host}/{owner_repo}.git"
    if "github.com" in origin_lower or origin.startswith("git@github.com"):
        return f"https://x-access-token:{encoded}@github.com/{owner_repo}.git"
    return None


def _origin_url(path: str, remote_name: str) -> str:
    return _run_git(path, "remote", "get-url", remote_name).stdout.strip()


def _host_token_for_origin(
    origin: str,
    *,
    github_token: str | None = None,
    gitlab_token: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (token, gitlab_base_url) appropriate for origin host."""
    origin_lower = origin.lower()
    if "gitlab" in origin_lower:
        return _resolve_gitlab_token(gitlab_token), settings.gitlab_base_url
    if "github.com" in origin_lower or origin.startswith("git@github.com"):
        return _resolve_github_token(github_token), None
    return None, None


def _authenticated_fetch_target(
    path: str,
    remote_name: str,
    *,
    github_token: str | None = None,
    gitlab_token: str | None = None,
) -> str:
    origin = _origin_url(path, remote_name)
    token, gitlab_base = _host_token_for_origin(origin, github_token=github_token, gitlab_token=gitlab_token)
    if token:
        auth = _authenticated_https_remote(origin, token, gitlab_base_url=gitlab_base)
        if auth:
            return auth
    return remote_name


async def create_pull_request(
    repository_path: str,
    *,
    title: str,
    body: str,
    base_branch: str | None = None,
    head_branch: str | None = None,
    remote: str | None = None,
    github_token: str | None = None,
    gitlab_token: str | None = None,
    gitlab_base_url: str | None = None,
) -> dict:
    root = _repo_path(repository_path)
    path = str(root)
    remote_name = remote or settings.git_remote
    head = head_branch or current_branch(path)
    base = base_branch or settings.git_base_branch or "main"
    origin = _run_git(path, "remote", "get-url", remote_name).stdout.strip()
    owner_repo = _owner_repo_from_origin(origin)
    if not owner_repo:
        return {
            "number": 0,
            "title": title,
            "url": f"file://{root}",
            "status": "LOCAL",
        }

    origin_lower = origin.lower()
    if "gitlab" in origin_lower:
        token = _resolve_gitlab_token(gitlab_token)
        host = (gitlab_base_url or settings.gitlab_base_url or os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")).rstrip("/")
        return await _create_gitlab_mr(owner_repo, title, body, base, head, token, host)

    if "github.com" in origin_lower or origin.startswith("git@github.com"):
        token = _resolve_github_token(github_token)
        return await _create_github_pr(owner_repo, title, body, base, head, token)

    return {
        "number": 0,
        "title": title,
        "url": f"file://{root}",
        "status": "LOCAL",
    }


async def _create_github_pr(
    owner_repo: str,
    title: str,
    body: str,
    base: str,
    head: str,
    token: str | None,
) -> dict:
    compare_url = f"https://github.com/{owner_repo}/compare/{base}...{head}"
    if not token:
        return {"number": 0, "title": title, "url": compare_url, "status": "DRAFT"}

    url = f"https://api.github.com/repos/{owner_repo}/pulls"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"title": title, "body": body, "head": head, "base": base},
        )
    if response.status_code >= 400:
        raise GitError(f"GitHub PR creation failed: HTTP {response.status_code} {response.text[:240]}")
    data = response.json()
    return {
        "number": int(data.get("number") or 0),
        "title": str(data.get("title") or title),
        "url": str(data.get("html_url") or compare_url),
        "status": "OPEN",
    }


async def _create_gitlab_mr(
    project_path: str,
    title: str,
    body: str,
    base: str,
    head: str,
    token: str | None,
    base_url: str,
) -> dict:
    encoded = urllib.parse.quote(project_path, safe="")
    web_url = (
        f"{base_url}/{project_path}/-/merge_requests/new"
        f"?merge_request[source_branch]={urllib.parse.quote(head)}"
        f"&merge_request[target_branch]={urllib.parse.quote(base)}"
    )
    if not token:
        return {"number": 0, "title": title, "url": web_url, "status": "DRAFT"}

    api_url = f"{base_url}/api/v4/projects/{encoded}/merge_requests"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            api_url,
            headers={"PRIVATE-TOKEN": token},
            json={"title": title, "description": body, "source_branch": head, "target_branch": base},
        )
    if response.status_code >= 400:
        raise GitError(f"GitLab MR creation failed: HTTP {response.status_code} {response.text[:240]}")
    data = response.json()
    return {
        "number": int(data.get("iid") or data.get("id") or 0),
        "title": str(data.get("title") or title),
        "url": str(data.get("web_url") or web_url),
        "status": "OPEN",
    }
