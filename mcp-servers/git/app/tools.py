from __future__ import annotations

from typing import Any, Awaitable, Callable

from . import git_ops

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


async def _health(_arguments: dict[str, Any]) -> dict[str, Any]:
    print("health check");
    return {"status": "ok", "service": "aidlc-git-mcp"}


async def _analyze(arguments: dict[str, Any]) -> dict[str, Any]:
    repository_path = arguments.get("repository_path")
    if not repository_path:
        raise ValueError("repository_path is required")
    return git_ops.analyze_repository(str(repository_path))


async def _branch(arguments: dict[str, Any]) -> dict[str, Any]:
    repository_path = arguments.get("repository_path")
    print("_branch called");
    jira_key = arguments.get("jira_key")
    summary = arguments.get("summary")
    print(f"repository_path: {repository_path}, jira_key: {jira_key}, summary: {summary}");
    if not repository_path or not jira_key or not summary:
        raise ValueError("repository_path, jira_key, and summary are required")
    return git_ops.create_branch(
        str(repository_path),
        str(jira_key),
        str(summary),
        base_branch=arguments.get("base_branch"),
        branch_name=arguments.get("branch_name"),
        remote=arguments.get("remote"),
    )


async def _write(arguments: dict[str, Any]) -> dict[str, Any]:
    repository_path = arguments.get("repository_path")
    files = arguments.get("files")
    if not repository_path or not isinstance(files, list):
        raise ValueError("repository_path and files are required")
    return git_ops.write_files(str(repository_path), files)


async def _push(arguments: dict[str, Any]) -> dict[str, Any]:
    repository_path = arguments.get("repository_path")
    if not repository_path:
        raise ValueError("repository_path is required")
    return git_ops.push_branch(
        str(repository_path),
        branch_name=arguments.get("branch_name") or arguments.get("head_branch"),
        remote=arguments.get("remote"),
        github_token=arguments.get("github_token"),
        gitlab_token=arguments.get("gitlab_token"),
    )


async def _pr(arguments: dict[str, Any]) -> dict[str, Any]:
    repository_path = arguments.get("repository_path")
    title = arguments.get("title")
    body = arguments.get("body", "")
    if not repository_path or not title:
        raise ValueError("repository_path and title are required")
    return await git_ops.create_pull_request(
        str(repository_path),
        title=str(title),
        body=str(body),
        base_branch=arguments.get("base_branch"),
        head_branch=arguments.get("head_branch"),
        remote=arguments.get("remote"),
        github_token=arguments.get("github_token"),
        gitlab_token=arguments.get("gitlab_token"),
        gitlab_base_url=arguments.get("gitlab_base_url"),
    )


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "health": _health,
    "analyze_repository": _analyze,
    "create_branch": _branch,
    "write_files": _write,
    "push_branch": _push,
    "create_pull_request": _pr,
}


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = TOOL_REGISTRY.get(name)
    if not handler:
        raise KeyError(f"Unknown tool: {name}")
    result = handler(arguments)
    if hasattr(result, "__await__"):
        return await result  # type: ignore[misc]
    return result  # type: ignore[return-value]
