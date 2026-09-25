from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.connection_models import GitConnectionConfig, JiraConnectionConfig, SessionConnection
from app.jira_create_models import CreateJiraIssueLinkRequest, CreateJiraIssueRequest, JiraCreateMetadata, ParsedJiraField
from app.jira_create_service import create_issue
from app.jira_issue_link_payload import build_issue_link_payload


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_create_issue_partial_success_when_link_fails() -> None:
    session = SessionConnection(
        jira=JiraConnectionConfig(
            mode="direct",
            base_url="https://jira.example.com",
            email="u@example.com",
            api_token="token",
            api_version="2",
        ),
        git=GitConnectionConfig(mode="direct", repository_path="/tmp/repo"),
    )
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="20",
        fields={"summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text")},
        sorted_tabs=[],
    )
    create_calls = {"count": 0}

    async def fake_request(_config, method, path, **kwargs):
        if method == "POST" and path == "/issue":
            create_calls["count"] += 1
            return FakeResponse(201, {"key": "SCR-9", "id": "1"})
        if method == "POST" and path == "/issueLink":
            return FakeResponse(400, {"errorMessages": ["link failed"]})
        raise AssertionError(f"unexpected {method} {path}")

    with patch("app.jira_create_service.get_create_metadata", AsyncMock(return_value=metadata)):
        with patch("app.jira_create_service.direct_jira._request", fake_request):
            result = await create_issue(
                session,
                CreateJiraIssueRequest(
                    project_id="10",
                    issue_type_id="20",
                    fields={"summary": "A"},
                    issue_links=[
                        CreateJiraIssueLinkRequest(
                            link_type_id="1",
                            target_issue_key="SCR-1",
                            new_issue_role="outward",
                        )
                    ],
                ),
            )
    assert create_calls["count"] == 1
    assert result.key == "SCR-9"
    assert result.partial_success is True
    assert result.post_create_operations[0].success is False


@pytest.mark.asyncio
async def test_create_issue_fails_without_key_when_issue_create_fails() -> None:
    session = SessionConnection(
        jira=JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@example.com", api_token="token"),
        git=GitConnectionConfig(mode="direct", repository_path="/tmp/repo"),
    )
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="20",
        fields={"summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text")},
        sorted_tabs=[],
    )

    async def fake_request(_config, method, path, **kwargs):
        if method == "POST" and path == "/issue":
            return FakeResponse(400, {"errorMessages": ["bad"]})
        raise AssertionError(path)

    with patch("app.jira_create_service.get_create_metadata", AsyncMock(return_value=metadata)):
        with patch("app.jira_create_service.direct_jira._request", fake_request):
            with pytest.raises(HTTPException) as exc:
                await create_issue(
                    session,
                    CreateJiraIssueRequest(project_id="10", issue_type_id="20", fields={"summary": "A"}),
                )
    assert exc.value.status_code == 422


def test_link_direction_payload_matches_ui_semantics() -> None:
    outward = build_issue_link_payload(
        new_issue_key="NEW-1",
        target_issue_key="SCR-2",
        link_type_id="10",
        new_issue_role="outward",
    )
    inward = build_issue_link_payload(
        new_issue_key="NEW-1",
        target_issue_key="SCR-2",
        link_type_id="10",
        new_issue_role="inward",
    )
    assert outward["outwardIssue"]["key"] == "NEW-1"
    assert inward["inwardIssue"]["key"] == "NEW-1"
