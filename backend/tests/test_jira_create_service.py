from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.connection_models import GitConnectionConfig, JiraConnectionConfig, SessionConnection
from app.jira_create_models import CreateJiraIssueRequest, CreateJiraMetadataRequest, JiraCreateMetadata, ParsedJiraField
from app.jira_create_service import (
    _issue_type_eligible_for_create_dialog,
    _merge_create_sources,
    build_jira_fields_payload,
    create_issue,
    get_create_metadata,
    list_issue_types,
)
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


def test_issue_type_eligibility_excludes_subtasks_by_api_flag() -> None:
    assert _issue_type_eligible_for_create_dialog({"id": "1", "name": "Task", "subtask": False}) is True
    assert _issue_type_eligible_for_create_dialog({"id": "2", "name": "Sub-task", "subtask": True}) is False
    assert _issue_type_eligible_for_create_dialog({"id": "3", "name": "Sub-task", "hierarchyLevel": -1}) is False


@pytest.mark.asyncio
async def test_list_issue_types_preserves_order_and_excludes_subtasks() -> None:
    config = JiraConnectionConfig(
        mode="direct",
        base_url="https://jira.example.com",
        email="u@example.com",
        api_token="token",
        api_version="2",
    )
    payload = {
        "values": [
            {"id": "1", "name": "Epic", "subtask": False},
            {"id": "2", "name": "Task", "subtask": False},
            {"id": "3", "name": "Story", "subtask": False},
            {"id": "4", "name": "Sub-task", "subtask": True},
        ]
    }
    with patch(
        "app.jira_create_service.direct_jira._request",
        AsyncMock(return_value=FakeResponse(200, payload)),
    ):
        issue_types = await list_issue_types(config, "10")
    assert [item.name for item in issue_types] == ["Epic", "Task", "Story"]


@pytest.mark.asyncio
async def test_create_issue_requires_direct_mode() -> None:
    session = SessionConnection(
        jira=JiraConnectionConfig(mode="mcp", mcp_url="https://mcp", mcp_token="x"),
        git=GitConnectionConfig(mode="mcp", mcp_url="https://mcp", mcp_token="x"),
    )
    with pytest.raises(HTTPException) as exc:
        await create_issue(session, CreateJiraIssueRequest(project_id="1", issue_type_id="2", fields={}))
    assert exc.value.status_code == 503


def test_merge_create_sources_preserves_rest_allowed_values_when_quick_create_empty() -> None:
    rest_raw = {
        "fields": {
            "customfield_10020": {
                "id": "customfield_10020",
                "label": "Sprint",
                "schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"},
                "allowedValues": [{"id": 42, "name": "SCRUM Sprint 0"}],
                "editHtml": "<select></select>",
            }
        },
        "sortedTabs": [],
    }
    quick_raw = {
        "fields": {
            "customfield_10020": {
                "label": "Sprint",
                "allowedValues": [],
                "editHtml": '<select class="js-sprint-picker"></select>',
            }
        }
    }
    merged = _merge_create_sources(quick_raw, rest_raw)
    allowed = merged["fields"]["customfield_10020"]["allowedValues"]
    assert isinstance(allowed, list) and len(allowed) == 1
    assert allowed[0]["id"] == 42


def test_build_jira_payload_serializes_sprint_as_id_array() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="20",
        fields={
            "customfield_10020": ParsedJiraField(
                id="customfield_10020",
                label="Sprint",
                required=False,
                type="select",
                options=[__import__("app.jira_create_models", fromlist=["JiraFieldOption"]).JiraFieldOption(label="Sprint 0", value="42")],
                raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            )
        },
        sorted_tabs=[],
    )
    payload = build_jira_fields_payload(metadata, {"customfield_10020": "42"}, api_version="2")
    assert payload["customfield_10020"] == [42]


def test_coerce_sprint_rejects_unknown_numeric_id() -> None:
    from app.jira_create_models import JiraFieldOption
    from app.jira_create_service import _coerce_sprint_field_value

    field = ParsedJiraField(
        id="customfield_10020",
        label="Sprint",
        required=False,
        type="select",
        options=[JiraFieldOption(label="Future: Sprint 1", value="100")],
        raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
    )
    assert _coerce_sprint_field_value(field, "1") is None
    assert _coerce_sprint_field_value(field, "100") == 100


def test_build_jira_payload_coerces_sprint_label_to_numeric_id() -> None:
    from app.jira_create_models import JiraFieldOption
    from app.jira_create_service import normalize_sprint_form_values

    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="20",
        fields={
            "customfield_10020": ParsedJiraField(
                id="customfield_10020",
                label="Sprint",
                required=False,
                type="select",
                options=[
                    JiraFieldOption(label="Active: SCRUM Sprint 0", value="99"),
                    JiraFieldOption(label="Future: SCRUM Sprint 1", value="100"),
                ],
                raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            )
        },
        sorted_tabs=[],
    )
    normalized = normalize_sprint_form_values(metadata, {"customfield_10020": "Active: SCRUM Sprint 0"})
    assert normalized["customfield_10020"] == "99"
    payload = build_jira_fields_payload(metadata, normalized, api_version="2")
    assert payload["customfield_10020"] == [99]


@pytest.mark.asyncio
async def test_normalize_sprint_maps_createmeta_id_to_board_sprint() -> None:
    from unittest.mock import AsyncMock, patch

    from app.connection_models import JiraConnectionConfig
    from app.jira_create_models import JiraFieldOption
    from app.jira_create_service import normalize_sprint_form_values_with_board

    metadata = JiraCreateMetadata(
        project_id="10000",
        issue_type_id="10004",
        project_key="SCRUM",
        fields={
            "customfield_10020": ParsedJiraField(
                id="customfield_10020",
                label="Sprint",
                required=False,
                type="select",
                options=[
                    JiraFieldOption(label="Future: SCRUM Sprint 1", value="1"),
                ],
                raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    board_sprints = [
        {"label": "Future: SCRUM Sprint 1", "value": "123"},
        {"label": "Active: SCRUM Sprint 0", "value": "122"},
    ]
    with patch(
        "app.jira_create_service.fetch_project_board_sprints",
        AsyncMock(return_value=board_sprints),
    ):
        normalized = await normalize_sprint_form_values_with_board(
            config,
            metadata,
            {"customfield_10020": "1"},
            project_key="SCRUM",
            project_id="10000",
        )
    assert normalized["customfield_10020"] == "123"
