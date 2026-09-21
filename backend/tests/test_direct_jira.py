from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.connection_models import JiraConnectionConfig
from app.integrations import direct_jira


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {"content-type": "application/json"}
        self.text = text or ("" if payload is None else "json")

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, handler) -> None:
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url, **kwargs):
        return self._handler("GET", url, kwargs)

    async def request(self, method, url, **kwargs):
        return self._handler(method, url, kwargs)


def _config() -> JiraConnectionConfig:
    return JiraConnectionConfig(
        mode="direct",
        base_url="https://jiraims.rm.imshealth.com",
        email="user@example.com",
        api_token="secret-token|",
    )


@pytest.mark.asyncio
async def test_validate_falls_back_to_api_v2_bearer() -> None:
    calls: list[str] = []

    def handler(method: str, url: str, _kwargs):
        calls.append(f"{method} {url}")
        if url.endswith("/rest/api/3/myself"):
            return FakeResponse(404)
        if url.endswith("/rest/api/2/myself") and "Authorization" in _kwargs.get("headers", {}):
            return FakeResponse(200, {"displayName": "K User", "emailAddress": "user@example.com"})
        if url.endswith("/rest/api/2/myself"):
            return FakeResponse(401)
        raise AssertionError(url)

    with patch("app.integrations.direct_jira.httpx.AsyncClient", lambda **_kwargs: FakeClient(handler)):
        config = _config()
        message = await direct_jira.validate_connection(config)

    assert message == "Connected as K User"
    assert config.api_version == "2"
    assert config.auth_scheme == "bearer"


@pytest.mark.asyncio
async def test_fetch_issue_uses_resolved_server_api() -> None:
    def handler(method: str, url: str, _kwargs):
        if url.endswith("/myself"):
            return FakeResponse(200, {"displayName": "K User"})
        if url.endswith("/issue/ABC-1"):
            return FakeResponse(
                200,
                {
                    "key": "ABC-1",
                    "self": "https://jiraims.rm.imshealth.com/rest/api/2/issue/ABC-1",
                    "fields": {
                        "summary": "Fix login",
                        "description": "plain text",
                        "issuetype": {"name": "Bug"},
                        "priority": {"name": "High"},
                        "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate", "name": "In Progress"}},
                        "assignee": {"displayName": "Alex Chen", "emailAddress": "alex@example.com"},
                        "reporter": {"displayName": "Priya Nair"},
                        "labels": ["auth", "backend"],
                    },
                },
            )
        raise AssertionError(url)

    config = _config()
    config.api_version = "2"
    config.auth_scheme = "basic"
    with patch("app.integrations.direct_jira.httpx.AsyncClient", lambda **_kwargs: FakeClient(handler)):
        task = await direct_jira.fetch_issue(config, "abc-1")

    assert task.key == "ABC-1"
    assert task.summary == "Fix login"
    assert task.description == "plain text"
    assert task.status == "In Progress"
    assert task.status_category == "In Progress"
    assert task.assignee == "Alex Chen"
    assert task.assignee_email == "alex@example.com"
    assert task.reporter == "Priya Nair"
    assert task.labels == ["auth", "backend"]
    assert task.url == "https://jiraims.rm.imshealth.com/browse/ABC-1"


@pytest.mark.asyncio
async def test_validate_rejects_sso_html() -> None:
    def handler(_method: str, _url: str, _kwargs):
        return FakeResponse(200, headers={"content-type": "text/html"}, text="<!DOCTYPE html><html>Login</html>")

    with patch("app.integrations.direct_jira.httpx.AsyncClient", lambda **_kwargs: FakeClient(handler)):
        with pytest.raises(HTTPException) as exc:
            await direct_jira.validate_connection(_config())
    assert exc.value.status_code == 401
