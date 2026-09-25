from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .tools import dispatch_tool

router = APIRouter()


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "aidlc-git-mcp"}


@router.post("/tools/call")
async def tools_call(payload: ToolCallRequest) -> dict[str, Any]:
    try:
        result = await dispatch_tool(payload.name, payload.arguments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        from .git_ops import GitError

        if isinstance(exc, GitError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"result": result}


@router.post("/mcp/tools/call")
async def mcp_tools_call(payload: ToolCallRequest) -> dict[str, Any]:
    return await tools_call(payload)


app = FastAPI(title="AIDLC Git MCP Server", version="1.0.0")
app.include_router(router, prefix="/git")


@app.post("/git")
async def jsonrpc_fallback(request: Request) -> JSONResponse:
    """Supports ExternalMCPClient JSON-RPC fallback when posted to the base MCP URL."""
    body = await request.json()
    if not isinstance(body, dict) or body.get("method") != "tools/call":
        raise HTTPException(status_code=400, detail="Expected JSON-RPC tools/call")
    params = body.get("params") or {}
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not name:
        raise HTTPException(status_code=400, detail="Missing tool name")
    payload = ToolCallRequest(name=str(name), arguments=arguments if isinstance(arguments, dict) else {})
    response = await tools_call(payload)
    return JSONResponse({"jsonrpc": "2.0", "id": body.get("id", 1), "result": response.get("result")})
