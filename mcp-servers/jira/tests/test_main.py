from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "dev@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token-123")
    main._resolved_api_version = "3"
    main._resolved_auth_scheme = "basic"
    return TestClient(main.app)


def test_root_lists_tools(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "get_issue" in body["tools"]
    assert "health" in body["tools"]


def test_health_tool(client: TestClient) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"displayName": "Dev User"}

    with patch.object(main, "_jira_request", new=AsyncMock(return_value=mock_response)):
        response = client.post("/tools/call", json={"name": "health", "arguments": {}})

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "ok"
    assert "Dev User" in response.json()["result"]["jira"]


def test_get_issue(client: TestClient) -> None:
    issue: dict[str, Any] = {
        "key": "ABC-1",
        "fields": {"summary": "Demo", "description": "Desc", "issuetype": {"name": "Task"}},
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = issue

    with patch.object(main, "_jira_request", new=AsyncMock(return_value=mock_response)):
        response = client.post(
            "/tools/call",
            json={"name": "get_issue", "arguments": {"issue_key": "abc-1"}},
        )

    assert response.status_code == 200
    assert response.json()["result"]["key"] == "ABC-1"
    assert response.json()["result"]["fields"]["summary"] == "Demo"


def test_unknown_tool(client: TestClient) -> None:
    response = client.post("/tools/call", json={"name": "nope", "arguments": {}})
    assert response.status_code == 404


def test_header_token_used_when_env_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "dev@example.com")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    main._resolved_api_version = "3"
    main._resolved_auth_scheme = "basic"
    main._resolved_token = "from-ui"
    client = TestClient(main.app)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"displayName": "From UI"}

    with patch.object(main, "_jira_request", new=AsyncMock(return_value=mock_response)):
        response = client.post(
            "/tools/call",
            json={"name": "health", "arguments": {}},
            headers={"Authorization": "Bearer from-ui"},
        )

    assert response.status_code == 200
    assert "From UI" in response.json()["result"]["jira"]


def test_missing_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "dev@example.com")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    main._resolved_api_version = None
    main._resolved_auth_scheme = None
    main._resolved_token = None
    client = TestClient(main.app)

    response = client.post("/tools/call", json={"name": "health", "arguments": {}})
    assert response.status_code == 401
    assert "Jira API token is missing" in response.json()["detail"]


def test_quoted_header_token_is_stripped() -> None:
    assert main._token_from_authorization('Bearer "ATATT-example"') == "ATATT-example"


def test_request_token_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_API_TOKEN", "from-env")
    main._bind_request_identity("Bearer from-ui")
    assert main._jira_api_token() == "from-ui"


def test_request_site_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://env.example")
    monkeypatch.setenv("JIRA_EMAIL", "env@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "from-env")
    main._bind_request_identity("Bearer from-ui", "https://ui.example", "ui@example.com")
    base_url, email, token = main._require_jira_config()
    assert base_url == "https://ui.example"
    assert email == "ui@example.com"
    assert token == "from-ui"


def test_jsonrpc_fallback(client: TestClient) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"displayName": "Dev User"}

    with patch.object(main, "_jira_request", new=AsyncMock(return_value=mock_response)):
        response = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "health", "arguments": {}},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["result"]["status"] == "ok"


def test_transition_and_comment(client: TestClient) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_response.json.return_value = {}

    with patch.object(main, "_jira_request", new=AsyncMock(return_value=mock_response)):
        transition = client.post(
            "/tools/call",
            json={"name": "transition_issue", "arguments": {"issue_key": "ABC-1", "transition_id": "31"}},
        )
        comment = client.post(
            "/mcp/tools/call",
            json={"name": "add_comment", "arguments": {"key": "ABC-1", "body": "PR created"}},
        )

    assert transition.status_code == 200
    assert transition.json()["result"]["ok"] is True
    assert comment.status_code == 200
    assert comment.json()["result"]["ok"] is True
