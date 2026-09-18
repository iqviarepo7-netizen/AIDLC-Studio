from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from .config_loader import AppConfig, GuardrailsConfig


class GuardrailViolation(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class Guardrails:
    def __init__(self, config: GuardrailsConfig) -> None:
        self.config = config
        self._injection_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in [
                r"ignore\s+previous\s+instructions",
                r"disregard\s+all\s+prior",
                r"system\s+prompt",
            ]
        ]

    def validate_request(self, stage: str, logical_tool: str, arguments: dict[str, Any]) -> None:
        allowed = set(self.config.stage_tools.get(stage, []))
        if allowed and logical_tool not in allowed:
            raise GuardrailViolation(f"Tool '{logical_tool}' is not allowed in stage '{stage}'.")

        for key, value in arguments.items():
            if isinstance(value, str):
                self._scrub_text(value, field=key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "path" in item:
                        self._validate_path(str(item["path"]))

        if "path" in arguments:
            self._validate_path(str(arguments["path"]))
        if "files" in arguments and isinstance(arguments["files"], list):
            for item in arguments["files"]:
                if isinstance(item, dict) and "path" in item:
                    self._validate_path(str(item["path"]))

    def validate_response(self, logical_tool: str, response: dict[str, Any]) -> None:
        if "files" in response and isinstance(response["files"], list):
            for item in response["files"]:
                if not isinstance(item, dict):
                    raise GuardrailViolation("Invalid file payload returned by MCP.")
                path = item.get("path")
                content = item.get("content")
                if not isinstance(path, str) or not isinstance(content, str):
                    raise GuardrailViolation("MCP file entries must include path and content.")
                self._validate_path(path)
                if len(content.encode("utf-8")) > self.config.max_file_bytes:
                    raise GuardrailViolation(f"Generated file '{path}' exceeds configured size limit.")

        if logical_tool.endswith(".write") or logical_tool == "git.write":
            changed = response.get("changed_files", response.get("files", []))
            if isinstance(changed, list):
                for path in changed:
                    if isinstance(path, dict) and "path" in path:
                        self._validate_path(str(path["path"]))
                    elif isinstance(path, str):
                        self._validate_path(path)

    def scrub_jira_text(self, text: str | None) -> str:
        if not text:
            return ""
        cleaned = text
        for pattern in self._injection_patterns:
            cleaned = pattern.sub("[filtered]", cleaned)
        return cleaned

    def _scrub_text(self, text: str, field: str) -> None:
        for pattern in self._injection_patterns:
            if pattern.search(text):
                raise GuardrailViolation(f"Potential prompt injection detected in field '{field}'.")

    def _validate_path(self, path: str) -> None:
        normalized = path.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise GuardrailViolation(f"Unsafe path rejected: {path}")
        segments = normalized.split("/")
        for blocked in self.config.blocked_path_segments:
            if blocked in segments:
                raise GuardrailViolation(f"Blocked path segment in '{path}'.")


def guardrail_http_exception(error: GuardrailViolation) -> HTTPException:
    return HTTPException(status_code=422, detail=f"Guardrail blocked request: {error.message}")
