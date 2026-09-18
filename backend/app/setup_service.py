from __future__ import annotations

import httpx
from fastapi import HTTPException

from .config_loader import MCPServerConfig
from .connection_models import GitConnectionConfig, JiraConnectionConfig
from .integrations import direct_git, direct_jira
from .mcp.clients import ExternalMCPClient


async def validate_jira(config: JiraConnectionConfig) -> str:
    if config.mode == "direct":
        return await direct_jira.validate_connection(config)
    if not config.mcp_url:
        raise HTTPException(status_code=400, detail="Jira MCP URL is required for MCP mode.")
    await _ping_mcp(config.mcp_url, config.mcp_token)
    return "Jira MCP endpoint reachable"


async def validate_git(config: GitConnectionConfig) -> str:
    if config.mode == "direct":
        return direct_git.validate_connection(config)
    if not config.mcp_url:
        raise HTTPException(status_code=400, detail="Git MCP URL is required for MCP mode.")
    await _ping_mcp(config.mcp_url, config.mcp_token)
    return "Git MCP endpoint reachable"


async def _ping_mcp(server_url: str, auth_token: str | None) -> None:
    client = ExternalMCPClient()
    server = MCPServerConfig(server_url=server_url, auth_token=auth_token or "")
    try:
        await client.call_tool(server, "health", {})
    except HTTPException as exc:
        if exc.status_code not in {404, 502}:
            raise
        headers: dict[str, str] = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        async with httpx.AsyncClient(timeout=15.0) as http:
            response = await http.get(server_url.rstrip("/"), headers=headers)
        if response.status_code >= 500:
            raise HTTPException(status_code=502, detail="MCP server is not reachable.") from exc
