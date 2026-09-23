from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.connection_models import GitConnectionConfig, JiraConnectionConfig, SessionConnection
from app.jira_create_models import CreateJiraIssueRequest, CreateJiraMetadataRequest, JiraCreateMetadata, ParsedJiraField
from app.jira_create_service import build_jira_fields_payload, create_issue, get_create_metadata
from app.jira_create_validation import validate_select_values


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or "json"

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_get_create_metadata_normalizes_tabs() -> None:
    session = SessionConnection(
        jira=JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@example.com", api_token="token"),
        git=GitConnectionConfig(mode="direct", repository_path="/tmp/repo"),
    )
    raw = {
        "fields": {
            "summary": {"label": "Summary", "required": True, "editHtml": '<input type="text" />'},
        },
        "sortedTabs": [{"id": "jira-tab-main", "label": "Details", "position": 0, "fields": ["summary"]}],
    }
    rest_raw = {
        "fields": {
            "summary": {
                "id": "summary",
                "label": "Summary",
                "required": True,
                "editHtml": '<input type="text" />',
                "schema": {"type": "string"},
            }
        },
        "sortedTabs": [],
    }
    with patch("app.jira_create_service.fetch_rest_create_fields", AsyncMock(return_value=rest_raw)):
        with patch("app.jira_create_service.fetch_quick_create_metadata", AsyncMock(return_value=raw)):
            metadata = await get_create_metadata(session, CreateJiraMetadataRequest(project_id="10", issue_type_id="20"))
    assert metadata.sorted_tabs[0].label == "Details"
    assert metadata.fields["summary"].required is True


def test_build_jira_create_payload_and_select_validation() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="20",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "customfield_1": ParsedJiraField(
                id="customfield_1",
                label="Severity",
                required=False,
                type="select",
                options=[__import__("app.jira_create_models", fromlist=["JiraFieldOption"]).JiraFieldOption(label="High", value="1")],
            ),
        },
        sorted_tabs=[],
    )
    payload = build_jira_fields_payload(metadata, {"summary": "Bug", "customfield_1": "1"}, api_version="2")
    assert payload["project"] == {"id": "10"}
    assert payload["summary"] == "Bug"
    assert payload["customfield_1"] == {"id": "1"}
    errors = validate_select_values(metadata, {"customfield_1": "999"})
    assert "customfield_1" in errors


@pytest.mark.asyncio
async def test_create_issue_returns_key_without_running_pipeline() -> None:
    session = SessionConnection(
        jira=JiraConnectionConfig(
            mode="direct",
            base_url="https://jira.example.com",
            email="u@example.com",
            api_token="token",
            api_version="2",
            auth_scheme="basic",
        ),
        git=GitConnectionConfig(mode="direct", repository_path="/tmp/repo"),
    )
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="20",
        fields={"summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text")},
        sorted_tabs=[],
    )

    async def fake_metadata(*_args, **_kwargs):
        return metadata

    with patch("app.jira_create_service.get_create_metadata", fake_metadata):
        with patch(
            "app.jira_create_service.direct_jira._request",
            AsyncMock(return_value=FakeResponse(201, {"key": "AAR8-132000", "id": "10001"})),
        ):
            result = await create_issue(session, CreateJiraIssueRequest(project_id="10", issue_type_id="20", fields={"summary": "Title"}))
    assert result.key == "AAR8-132000"


@pytest.mark.asyncio
async def test_create_issue_requires_direct_mode() -> None:
    session = SessionConnection(
        jira=JiraConnectionConfig(mode="mcp", mcp_url="https://mcp", mcp_token="x"),
        git=GitConnectionConfig(mode="mcp", mcp_url="https://mcp", mcp_token="x"),
    )
    with pytest.raises(HTTPException) as exc:
        await create_issue(session, CreateJiraIssueRequest(project_id="1", issue_type_id="2", fields={}))
    assert exc.value.status_code == 503
