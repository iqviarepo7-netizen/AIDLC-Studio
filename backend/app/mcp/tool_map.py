from __future__ import annotations

from typing import Any

from ..config_loader import AppConfig, MCPServerConfig


class ToolMap:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def resolve(self, server: str, logical_name: str) -> str:
        server_config = getattr(self.config.policy.mcp, server)
        tools = server_config.tools.model_dump()
        if logical_name not in tools:
            raise KeyError(f"Unknown logical MCP tool '{logical_name}' for server '{server}'.")
        return tools[logical_name]

    def logical_name(self, server: str, tool_key: str) -> str:
        return f"{server}.{tool_key}"

    def server_config(self, server: str) -> MCPServerConfig:
        return getattr(self.config.policy.mcp, server)
