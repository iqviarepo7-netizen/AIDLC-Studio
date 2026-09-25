from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from ..config_loader import MCPServerConfig


def _http_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("detail")
            if detail is not None:
                return str(detail)
    except ValueError:
        pass
    text = (response.text or "").strip()
    return text[:500] if text else f"HTTP {response.status_code}"


class ExternalMCPClient:
    """HTTP client for external MCP servers exposing a tools/call endpoint."""

    async def call_tool(self, server: MCPServerConfig, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not server.server_url:
            raise HTTPException(status_code=503, detail="MCP server URL is not configured.")
        url = server.server_url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if server.auth_token:
            headers["Authorization"] = f"Bearer {server.auth_token}"

        payload = {"name": tool_name, "arguments": arguments}
        endpoints = [f"{url}/tools/call", f"{url}/mcp/tools/call", url]

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            for endpoint in endpoints[:2]:
                try:
                    response = await client.post(endpoint, headers=headers, json=payload)
                    if response.is_error:
                        detail = _http_error_detail(response)
                        raise HTTPException(
                            status_code=502,
                            detail=f"MCP tool call failed: {detail}",
                        )
                    body = response.json()
                    if isinstance(body, dict) and "result" in body:
                        result = body["result"]
                        return result if isinstance(result, dict) else {"result": result}
                    if isinstance(body, dict):
                        return body
                except HTTPException:
                    raise
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    continue

            try:
                response = await client.post(
                    url,
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": payload},
                )
                if response.is_error:
                    detail = _http_error_detail(response)
                    raise HTTPException(
                        status_code=502,
                        detail=f"MCP tool call failed: {detail}",
                    )
                body = response.json()
                if isinstance(body, dict) and "result" in body:
                    result = body["result"]
                    return result if isinstance(result, dict) else {"result": result}
            except HTTPException:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc

        detail = str(last_error) if last_error else "Unknown MCP transport error"
        raise HTTPException(status_code=502, detail=f"MCP tool call failed: {detail}")
