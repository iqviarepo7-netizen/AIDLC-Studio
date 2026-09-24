"""HTTP Jira MCP server compatible with AIDLC Studio's ExternalMCPClient.

Exposes POST /tools/call (and /mcp/tools/call) with tools:
  health, get_issue, transition_issue, add_comment

Credentials live in this process's .env — not in the Studio Connect form.
Studio Connect field "MCP URL" should be: http://localhost:9001
"""

from __future__ import annotations

import os
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

load_dotenv()

AuthScheme = Literal["basic", "bearer"]
ApiVersion = Literal["2", "3"]

app = FastAPI(title="AIDLC Jira MCP", version="1.0.0")

# Resolved on first successful /myself probe and reused for later calls.
_resolved_api_version: ApiVersion | None = None
_resolved_auth_scheme: AuthScheme | None = None


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _require_jira_config() -> tuple[str, str, str]:
    base_url = _env("JIRA_BASE_URL").rstrip("/")
    email = _env("JIRA_EMAIL")
    token = _env("JIRA_API_TOKEN").rstrip("|").strip()
    if not base_url or not email or not token:
        raise HTTPException(
            status_code=503,
            detail="Jira MCP is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN.",
        )
    return base_url, email, token


def _check_mcp_auth(authorization: str | None) -> None:
    expected = _env("MCP_AUTH_TOKEN")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization bearer token.")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid MCP bearer token.")


def _auth_for(email: str, token: str, scheme: AuthScheme) -> tuple[dict[str, str], tuple[str, str] | None]:
    if scheme == "basic":
        return {}, (email, token)
    return {"Authorization": f"Bearer {token}"}, None


def _is_html(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" in content_type:
        return True
    text = response.text[:80].lstrip().lower()
    return text.startswith("<!doctype") or text.startswith("<html")


async def _ensure_resolved(base_url: str, email: str, token: str) -> tuple[ApiVersion, AuthScheme]:
    global _resolved_api_version, _resolved_auth_scheme
    if _resolved_api_version and _resolved_auth_scheme:
        return _resolved_api_version, _resolved_auth_scheme

    forced_version = _env("JIRA_API_VERSION")
    forced_scheme = _env("JIRA_AUTH_SCHEME")
    versions: list[ApiVersion] = [forced_version] if forced_version in {"2", "3"} else ["3", "2"]  # type: ignore[list-item]
    schemes: list[AuthScheme] = [forced_scheme] if forced_scheme in {"basic", "bearer"} else ["basic", "bearer"]  # type: ignore[list-item]

    last_status: int | None = None
    saw_html = False
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        for version in versions:
            for scheme in schemes:
                headers = {"Accept": "application/json"}
                extra, auth = _auth_for(email, token, scheme)
                headers.update(extra)
                url = f"{base_url}/rest/api/{version}/myself"
                response = await client.get(url, auth=auth, headers=headers)
                last_status = response.status_code
                if response.status_code in {301, 302, 303, 307, 308} or _is_html(response):
                    saw_html = True
                    continue
                if response.status_code in {401, 403, 404}:
                    continue
                if response.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"Jira connection failed: HTTP {response.status_code}.")
                _resolved_api_version = version
                _resolved_auth_scheme = scheme
                return version, scheme

    if saw_html:
        raise HTTPException(
            status_code=401,
            detail="Jira returned a login page instead of the REST API. Check VPN/SSO and API token.",
        )
    if last_status in {401, 403}:
        raise HTTPException(status_code=401, detail="Jira authentication failed. Check email and API token.")
    raise HTTPException(status_code=502, detail=f"Jira connection failed: HTTP {last_status or 'unknown'}.")


async def _jira_request(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    base_url, email, token = _require_jira_config()
    version, scheme = await _ensure_resolved(base_url, email, token)
    headers = {"Accept": "application/json"}
    extra, auth = _auth_for(email, token, scheme)
    headers.update(extra)
    url = f"{base_url}/rest/api/{version}{path}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.request(method, url, auth=auth, headers=headers, json=json)
    if response.status_code in {301, 302, 303, 307, 308} or _is_html(response):
        raise HTTPException(
            status_code=401,
            detail="Jira returned a login page instead of the REST API. Check VPN/SSO and API token.",
        )
    return response


def _comment_payload(comment: str, api_version: ApiVersion) -> dict[str, Any]:
    if api_version == "2":
        return {"body": comment}
    return {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}],
        }
    }


def _issue_key(arguments: dict[str, Any]) -> str:
    key = (arguments.get("issue_key") or arguments.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="issue_key (or key) is required.")
    return key.upper()


async def _tool_health(_: dict[str, Any]) -> dict[str, Any]:
    # Optional live check when credentials are present; otherwise still report process up.
    if _env("JIRA_BASE_URL") and _env("JIRA_EMAIL") and _env("JIRA_API_TOKEN"):
        try:
            response = await _jira_request("GET", "/myself", timeout=15.0)
            if response.status_code < 400:
                data = response.json()
                display = data.get("displayName") or data.get("emailAddress") or "authenticated user"
                return {"status": "ok", "server": "jira", "jira": f"Connected as {display}"}
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — surface connectivity issues cleanly
            raise HTTPException(status_code=502, detail=f"Jira health check failed: {exc}") from exc
    return {"status": "ok", "server": "jira", "jira": "credentials not set"}


async def _tool_get_issue(arguments: dict[str, Any]) -> dict[str, Any]:
    key = _issue_key(arguments)
    response = await _jira_request("GET", f"/issue/{key}")
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Jira issue {key} was not found.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira fetch failed: HTTP {response.status_code}.")
    return response.json()


async def _tool_transition_issue(arguments: dict[str, Any]) -> dict[str, Any]:
    key = _issue_key(arguments)
    transition_id = str(arguments.get("transition_id") or "").strip()
    if not transition_id:
        raise HTTPException(status_code=400, detail="transition_id is required.")
    response = await _jira_request(
        "POST",
        f"/issue/{key}/transitions",
        json={"transition": {"id": transition_id}},
        timeout=20.0,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira transition failed: HTTP {response.status_code}.")
    return {"ok": True, "issue_key": key, "transition_id": transition_id}


async def _tool_add_comment(arguments: dict[str, Any]) -> dict[str, Any]:
    key = _issue_key(arguments)
    comment = str(arguments.get("comment") or arguments.get("body") or "").strip()
    if not comment:
        raise HTTPException(status_code=400, detail="comment (or body) is required.")
    base_url, email, token = _require_jira_config()
    version, _ = await _ensure_resolved(base_url, email, token)
    response = await _jira_request(
        "POST",
        f"/issue/{key}/comment",
        json=_comment_payload(comment, version),
        timeout=20.0,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira comment failed: HTTP {response.status_code}.")
    return {"ok": True, "issue_key": key}


TOOLS = {
    "health": _tool_health,
    "get_issue": _tool_get_issue,
    "transition_issue": _tool_transition_issue,
    "add_comment": _tool_add_comment,
}


async def _dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = TOOLS.get(name)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")
    result = await handler(arguments or {})
    return {"result": result}


@app.get("/")
async def root(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_mcp_auth(authorization)
    return {"status": "ok", "server": "jira-mcp", "tools": sorted(TOOLS)}


@app.post("/tools/call")
async def tools_call(body: ToolCallRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_mcp_auth(authorization)
    return await _dispatch(body.name, body.arguments)


@app.post("/mcp/tools/call")
async def mcp_tools_call(body: ToolCallRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_mcp_auth(authorization)
    return await _dispatch(body.name, body.arguments)


@app.post("/")
async def jsonrpc_or_tool_call(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Support Studio's JSON-RPC fallback: method tools/call with params {name, arguments}."""
    _check_mcp_auth(authorization)
    payload = await request.json()
    if isinstance(payload, dict) and payload.get("method") == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            raise HTTPException(status_code=400, detail="JSON-RPC tools/call requires params.name.")
        result = await _dispatch(str(name), arguments if isinstance(arguments, dict) else {})
        return {"jsonrpc": "2.0", "id": payload.get("id", 1), "result": result.get("result", result)}
    if isinstance(payload, dict) and "name" in payload:
        return await _dispatch(str(payload["name"]), payload.get("arguments") or {})
    raise HTTPException(status_code=400, detail="Expected tools/call payload.")
