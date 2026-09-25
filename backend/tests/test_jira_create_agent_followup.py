import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _stub_jira_form_normalization():
    async def _identity(config, metadata, values, **kwargs):
        return values

    with (
        patch("app.jira_create_service.normalize_sprint_form_values_with_board", side_effect=_identity),
        patch("app.jira_create_service.normalize_parent_form_values", side_effect=_identity),
    ):
        yield

from app.connection_models import JiraConnectionConfig
from app.jira_create_agent import analyze_requirement
from app.jira_create_agent_conversation import (
    extract_followup_field_updates,
    is_requirement_modification,
    merge_field_patch,
    should_use_field_patch_path,
)
from app.jira_create_models import (
    CreateJiraAgentMessage,
    CreateJiraAgentRequest,
    JiraCreateMetadata,
    JiraFieldOption,
    ParsedJiraField,
)


def _baseline_metadata() -> JiraCreateMetadata:
    return JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
            "duedate": ParsedJiraField(id="duedate", label="Due date", required=False, type="date"),
            "priority": ParsedJiraField(
                id="priority",
                label="Priority",
                required=False,
                type="priority",
                options=[
                    JiraFieldOption(label="High", value="2"),
                    JiraFieldOption(label="Medium", value="3"),
                ],
            ),
            "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user", searchable=True),
            "parent": ParsedJiraField(id="parent", label="Parent", required=False, type="parent", searchable=True),
            "customfield_story": ParsedJiraField(
                id="customfield_story", label="Story Points", required=False, type="number"
            ),
        },
        sorted_tabs=[],
    )


BASELINE_SUMMARY = "Add welcome popup to Run Pipeline"
BASELINE_DESCRIPTION = "Solution:\nShow popup.\n\nAcceptance Criteria:\nPopup appears."


def test_change_story_point_should_be_matches_story_points_field_label() -> None:
    metadata = _baseline_metadata()
    metadata.fields["customfield_story"] = ParsedJiraField(
        id="customfield_story", label="Story Points", required=False, type="number"
    )
    updates = extract_followup_field_updates(
        "change story point should be 15",
        metadata,
        pending_fields=[],
        pending_clarification_field_id=None,
    )
    assert updates == {"customfield_story": "15"}


@pytest.mark.asyncio
async def test_followup_story_points_update_when_form_already_complete() -> None:
    metadata = _baseline_metadata()
    metadata.fields["customfield_story"] = ParsedJiraField(
        id="customfield_story", label="Story Points", required=False, type="number"
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="initial requirement"),
            CreateJiraAgentMessage(role="assistant", content="ready"),
            CreateJiraAgentMessage(role="user", content="change story point should be 15"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": BASELINE_SUMMARY,
            "description": BASELINE_DESCRIPTION,
            "customfield_story": 5,
        },
        conversation_phase="ready_to_create",
    )
    response = await analyze_requirement(provider, metadata, request, config)
    provider.generate.assert_not_called()
    assert response.fields["customfield_story"] == "15"
    assert response.message.startswith("Updated Story Points to 15.")
    assert "All required Jira fields have values" not in response.message


def test_change_due_date_is_field_patch_not_requirement_update() -> None:
    metadata = _baseline_metadata()
    assert is_requirement_modification("change due date to next week saturday") is False
    updates = extract_followup_field_updates(
        "change due date to next week saturday",
        metadata,
        pending_fields=[],
        pending_clarification_field_id=None,
    )
    assert updates == {"duedate": "next week saturday"}


def test_ready_to_create_follow_up_uses_field_patch_path() -> None:
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="initial"),
            CreateJiraAgentMessage(role="assistant", content="ready"),
            CreateJiraAgentMessage(role="user", content="change due date to next week saturday"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={"summary": BASELINE_SUMMARY, "description": BASELINE_DESCRIPTION, "priority": "2"},
        conversation_phase="ready_to_create",
    )
    assert should_use_field_patch_path(request, "change due date to next week saturday") is True


def test_merge_field_patch_preserves_unmentioned_summary_and_description() -> None:
    metadata = _baseline_metadata()
    current = {
        "summary": BASELINE_SUMMARY,
        "description": BASELINE_DESCRIPTION,
        "priority": "2",
    }
    resolved = {
        **current,
        "duedate": "2026-10-03",
        "summary": "Regenerated summary",
        "description": "Solution:\nLeaked.\n\nAcceptance Criteria:\nLeaked.",
    }
    merged = merge_field_patch(metadata, current, resolved, {"duedate"}, set())
    assert merged["summary"] == BASELINE_SUMMARY
    assert merged["description"] == BASELINE_DESCRIPTION
    assert merged["priority"] == "2"
    assert merged["duedate"] == "2026-10-03"


@pytest.mark.asyncio
async def test_followup_due_date_does_not_regenerate_summary_or_description() -> None:
    from datetime import date, timedelta

    metadata = _baseline_metadata()
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="initial requirement"),
            CreateJiraAgentMessage(role="assistant", content="ready"),
            CreateJiraAgentMessage(role="user", content="change due date to next week saturday"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": BASELINE_SUMMARY,
            "description": BASELINE_DESCRIPTION,
            "priority": "2",
        },
        conversation_phase="ready_to_create",
    )
    response = await analyze_requirement(provider, metadata, request, config)
    provider.generate.assert_not_called()
    assert response.fields["summary"] == BASELINE_SUMMARY
    assert response.fields["description"] == BASELINE_DESCRIPTION
    assert response.fields["priority"] == "2"
    today = date.today()
    expected = (today + timedelta(days=(7 - today.weekday())) + timedelta(days=5)).isoformat()
    assert response.fields["duedate"] == expected


@pytest.mark.asyncio
async def test_followup_change_summary_only_updates_summary() -> None:
    metadata = _baseline_metadata()
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="initial"),
            CreateJiraAgentMessage(role="assistant", content="ready"),
            CreateJiraAgentMessage(role="user", content="change summary to Pipeline popup"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": BASELINE_SUMMARY,
            "description": BASELINE_DESCRIPTION,
        },
        conversation_phase="ready_to_create",
    )
    response = await analyze_requirement(provider, metadata, request, config)
    provider.generate.assert_not_called()
    assert response.fields["summary"] == "Pipeline popup"
    assert response.fields["description"] == BASELINE_DESCRIPTION


@pytest.mark.asyncio
async def test_requirement_update_regenerates_summary_and_description_preserves_jira_fields() -> None:
    metadata = _baseline_metadata()
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    provider.generate.return_value = json.dumps(
        {
            "mode": "requirement_update",
            "summary": "Show welcome home alert when Run Pipeline is clicked",
            "description": {
                "solution": "When Run Pipeline is clicked, show a browser alert with welcome home.",
                "acceptanceCriteria": "Alert appears with welcome home; no popup is shown.",
            },
            "fieldUpdates": {},
            "clarification": None,
        }
    )
    initial_requirement = "show welcome home popup when Run Pipeline is clicked"
    follow_up = "change in requirement, need to show alert not popup"
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content=initial_requirement),
            CreateJiraAgentMessage(role="assistant", content="ready"),
            CreateJiraAgentMessage(role="user", content=follow_up),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": BASELINE_SUMMARY,
            "description": BASELINE_DESCRIPTION,
            "priority": "2",
            "assignee": "acc-1",
        },
        conversation_phase="ready_to_create",
    )
    response = await analyze_requirement(provider, metadata, request, config)
    provider.generate.assert_called_once()
    prompt = provider.generate.call_args[0][0]
    assert initial_requirement in prompt
    assert BASELINE_SUMMARY in prompt
    assert "alert not popup" in prompt.lower()
    assert "alert" in response.fields["summary"].lower()
    assert "popup" not in response.fields["summary"].lower()
    assert "alert" in response.fields["description"].lower()
    assert response.fields["priority"] == "2"
    assert response.fields["assignee"] == "acc-1"


@pytest.mark.asyncio
async def test_followup_requirement_extension_preserves_unrelated_fields() -> None:
    metadata = _baseline_metadata()
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    provider.generate.return_value = json.dumps(
        {
            "mode": "requirement_update",
            "summary": "Welcome alert on Run Pipeline with auto-close",
            "description": {
                "solution": "Show alert on Run Pipeline; auto-close after 5 seconds.",
                "acceptanceCriteria": "Alert closes after 5 seconds.",
            },
            "fieldUpdates": {},
            "clarification": None,
        }
    )
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="show welcome home alert when Run Pipeline is clicked"),
            CreateJiraAgentMessage(role="assistant", content="ready"),
            CreateJiraAgentMessage(role="user", content="also make the alert close after 5 seconds"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": "Show welcome home alert when Run Pipeline is clicked",
            "description": "Solution:\nAlert.\n\nAcceptance Criteria:\nAlert shows.",
            "priority": "2",
            "customfield_story": 3,
        },
        conversation_phase="ready_to_create",
    )
    response = await analyze_requirement(provider, metadata, request, config)
    provider.generate.assert_called_once()
    assert "5" in response.fields["description"] or "close" in response.fields["description"].lower()
    assert response.fields["priority"] == "2"
    assert response.fields["customfield_story"] == 3
