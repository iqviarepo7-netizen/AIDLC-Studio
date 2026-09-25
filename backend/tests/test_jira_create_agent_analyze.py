from unittest.mock import AsyncMock, patch

import pytest

from app.connection_models import JiraConnectionConfig
from app.jira_create_agent import analyze_requirement
from app.jira_create_models import (
    CreateJiraAgentMessage,
    CreateJiraAgentRequest,
    JiraCreateMetadata,
    JiraFieldOption,
    ParsedJiraField,
    PendingAgentField,
)


@pytest.mark.asyncio
async def test_pending_clarification_reply_resolves_assignee_without_llm() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
            "assignee": ParsedJiraField(
                id="assignee",
                label="Assignee",
                required=False,
                type="user",
                searchable=True,
                options=[],
            ),
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="assign to xyz"),
            CreateJiraAgentMessage(role="assistant", content="Please provide a valid Assignee."),
            CreateJiraAgentMessage(role="user", content="navi"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": "Add welcome popup",
            "description": "Solution:\nShow popup.\n\nAcceptance Criteria:\nPopup appears.",
        },
        conversation_phase="field_resolution",
        pending_fields=[PendingAgentField(field_id="assignee", requested_value="xyz")],
        pending_clarification_field_id="assignee",
    )

    with patch(
        "app.jira_create_service.resolve_assignable_user_value",
        AsyncMock(return_value=("acc-navi", ["Navi User"])),
    ):
        response = await analyze_requirement(provider, metadata, request, config)

    provider.generate.assert_not_called()
    assert response.fields["assignee"] == "acc-navi"
    assert response.fields["summary"] == "Add welcome popup"
    assert response.conversation_phase == "ready_to_create"


@pytest.mark.asyncio
async def test_field_resolution_sprint_answer_preserves_summary() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
            "customfield_sprint": ParsedJiraField(
                id="customfield_sprint",
                label="Sprint",
                required=False,
                type="select",
                options=[
                    JiraFieldOption(label="Active: SCRUM Sprint 0", value="42"),
                    JiraFieldOption(label="Future: SCRUM Sprint 1", value="1"),
                ],
                raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            ),
            "assignee": ParsedJiraField(
                id="assignee",
                label="Assignee",
                required=False,
                type="user",
                searchable=True,
                options=[],
            ),
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="initial"),
            CreateJiraAgentMessage(role="assistant", content="need sprint and assignee"),
            CreateJiraAgentMessage(role="user", content="Active: SCRUM Sprint 0"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": "Add welcome popup",
            "description": "Solution:\nShow popup.\n\nAcceptance Criteria:\nPopup appears.",
            "assignee": "mohan",
        },
        conversation_phase="field_resolution",
        pending_fields=[
            PendingAgentField(field_id="customfield_sprint", requested_value="active sprint"),
            PendingAgentField(field_id="assignee", requested_value="mohan"),
        ],
    )

    with patch(
        "app.jira_create_service.search_assignable_users",
        AsyncMock(return_value=[]),
    ):
        response = await analyze_requirement(provider, metadata, request, config)

    provider.generate.assert_not_called()
    assert response.fields["summary"] == "Add welcome popup"
    assert response.fields["customfield_sprint"] == "42"
    assert "Sprint" not in response.fields["summary"]


def _exact_prompt_metadata() -> JiraCreateMetadata:
    return JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        project_key="MK",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
            "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user", searchable=True),
            "duedate": ParsedJiraField(id="duedate", label="Due date", required=False, type="date"),
            "customfield_start": ParsedJiraField(id="customfield_start", label="Start date", required=False, type="date"),
            "priority": ParsedJiraField(
                id="priority",
                label="Priority",
                required=False,
                type="priority",
                options=[JiraFieldOption(label="High", value="2"), JiraFieldOption(label="Low", value="1")],
            ),
            "labels": ParsedJiraField(id="labels", label="Labels", required=False, type="labels"),
            "parent": ParsedJiraField(
                id="parent",
                label="Parent",
                required=False,
                type="parent",
                searchable=True,
                options=[JiraFieldOption(label="SCRUM-5 — intended", value="SCRUM-5")],
            ),
            "parentId": ParsedJiraField(id="parentId", label="Parent", required=False, type="parent", searchable=True),
            "customfield_sprint": ParsedJiraField(
                id="customfield_sprint",
                label="Sprint",
                required=False,
                type="select",
                options=[
                    JiraFieldOption(label="Active: Sprint 0", value="42"),
                    JiraFieldOption(label="Future: Sprint 1", value="99"),
                ],
                raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            ),
            "customfield_story": ParsedJiraField(
                id="customfield_story",
                label="Story Points",
                required=False,
                type="number",
            ),
        },
        sorted_tabs=[],
    )


EXACT_PROMPT = (
    "add a popup after when user clicks run pipeline. popup should say welcome home. "
    "assign it to iqvia. start date should be 6 days from today. priority is high. "
    "add labels test and develop. mark it as future sprint. due date as next week friday. "
    "parent jira is scrum 5. story point is 5. "
    "linked work items is that this jira issue clone scrum 8"
)


@pytest.mark.asyncio
async def test_exact_prompt_binds_fields_without_leaking_into_description() -> None:
    from datetime import date, timedelta

    from app.jira_create_models import JiraIssueLinkTypeOption, JiraIssueSearchOption

    metadata = _exact_prompt_metadata()
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    provider.generate = AsyncMock(
        return_value="""
        {
          "mode": "initial_requirement",
          "summary": "Add welcome home popup to Run Pipeline",
          "description": {
            "solution": "When the user clicks Run Pipeline, show a popup that says welcome home.",
            "acceptanceCriteria": "Clicking Run Pipeline opens the popup. Assignee is IQVIA. Story points are 5."
          },
          "fields": {}
        }
        """
    )
    request = CreateJiraAgentRequest(
        messages=[CreateJiraAgentMessage(role="user", content=EXACT_PROMPT)],
        project_id="10",
        issue_type_id="2",
        current_values={},
    )

    async def fake_search_issues(_config, *, project_id, query="", max_results=20):
        canonical = query.strip().upper().replace(" ", "-")
        if canonical == "SCRUM-5":
            return [
                JiraIssueSearchOption(label="SCRUM-7 — unrelated", value="SCRUM-7"),
                JiraIssueSearchOption(label="SCRUM-5 — intended", value="SCRUM-5"),
            ]
        if canonical == "SCRUM-8":
            return [
                JiraIssueSearchOption(label="SCRUM-7 — unrelated", value="SCRUM-7"),
                JiraIssueSearchOption(label="SCRUM-8 — source", value="SCRUM-8"),
            ]
        return [JiraIssueSearchOption(label="SCRUM-7 — unrelated", value="SCRUM-7")]

    with (
        patch(
            "app.jira_create_service.resolve_assignable_user_value",
            AsyncMock(return_value=("acc-iqvia", ["IQVIA Test"])),
        ),
        patch("app.jira_create_service.fetch_issue_id_for_key", AsyncMock(return_value="10005")),
        patch("app.jira_create_service.search_issues", AsyncMock(side_effect=fake_search_issues)),
        patch(
            "app.jira_create_service.list_issue_link_types",
            AsyncMock(
                return_value=[
                    JiraIssueLinkTypeOption(id="10000", name="Blocks", inward="is blocked by", outward="blocks"),
                    JiraIssueLinkTypeOption(id="10001", name="Cloners", inward="is cloned by", outward="clones"),
                ]
            ),
        ),
    ):
        response = await analyze_requirement(provider, metadata, request, config)

    description = str(response.fields["description"]).lower()
    assert "assignee" not in description
    assert "story point" not in description
    assert "iqvia" not in description
    assert "priority" not in description
    assert "scrum-5" not in description
    assert "scrum 8" not in description
    assert "solution:" in description
    assert "welcome home" in description or "run pipeline" in description
    assert response.fields["assignee"] == "acc-iqvia"
    assert response.fields["priority"] == "2"
    assert response.fields["labels"] == ["test", "develop"]
    assert response.fields["customfield_sprint"] == "99"
    assert response.fields["parent"] == "SCRUM-5"
    assert response.fields["parentId"] == "10005"
    assert str(response.fields["customfield_story"]) == "5"
    today = date.today()
    assert response.fields["customfield_start"] == (today + timedelta(days=6)).isoformat()
    assert response.fields["duedate"] == (today + timedelta(days=(7 - today.weekday())) + timedelta(days=4)).isoformat()
    assert len(response.issue_links) == 1
    assert response.issue_links[0].link_type_id == "10001"
    assert response.issue_links[0].target_issue_key == "SCRUM-8"
    assert response.issue_links[0].new_issue_role == "outward"


@pytest.mark.asyncio
async def test_field_resolution_does_not_regenerate_summary_or_description() -> None:
    from app.jira_create_models import JiraIssueSearchOption

    metadata = _exact_prompt_metadata()
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    provider = AsyncMock()
    original_description = "Solution:\nShow popup.\n\nAcceptance Criteria:\nPopup appears."
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="initial"),
            CreateJiraAgentMessage(role="assistant", content="need parent"),
            CreateJiraAgentMessage(role="user", content="scrum 5"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": "Add welcome popup",
            "description": original_description,
        },
        conversation_phase="field_resolution",
        pending_fields=[PendingAgentField(field_id="parent", requested_value="scrum 5")],
        pending_clarification_field_id="parent",
    )
    with (
        patch("app.jira_create_service.fetch_issue_id_for_key", AsyncMock(return_value="10005")),
        patch(
            "app.jira_create_service.search_issues",
            AsyncMock(
                return_value=[
                    JiraIssueSearchOption(label="SCRUM-7 — unrelated", value="SCRUM-7"),
                    JiraIssueSearchOption(label="SCRUM-5 — intended", value="SCRUM-5"),
                ]
            ),
        ),
    ):
        response = await analyze_requirement(provider, metadata, request, config)

    provider.generate.assert_not_called()
    assert response.fields["summary"] == "Add welcome popup"
    assert response.fields["description"] == original_description
    assert response.fields["parent"] == "SCRUM-5"
    assert response.fields["parentId"] == "10005"
    assert response.fields["parentId"] == "10005"
