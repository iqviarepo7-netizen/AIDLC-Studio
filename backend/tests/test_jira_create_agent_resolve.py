from unittest.mock import AsyncMock, patch

import pytest

from app.connection_models import JiraConnectionConfig
from app.jira_create_models import JiraCreateMetadata, ParsedJiraField, JiraFieldOption
from app.jira_create_agent_resolve import resolve_agent_fields


@pytest.mark.asyncio
async def test_resolve_assignee_exact_match_wins() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        project_key="SCRUM",
        fields={
            "assignee": ParsedJiraField(
                id="assignee",
                label="Assignee",
                required=False,
                type="user",
                searchable=True,
                options=[],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")

    with patch(
        "app.jira_create_service.search_assignable_users",
        AsyncMock(
            return_value=[
                {"label": "Mohan Impelox", "value": "acc-1"},
                {"label": "IQVIA Test", "value": "acc-2"},
            ]
        ),
    ):
        resolved, missing = await resolve_agent_fields(
            config,
            metadata,
            {"assignee": "Mohan Impelox"},
            project_id="10",
            project_key="SCRUM",
        )
    assert resolved["assignee"] == "acc-1"
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_assignee_uses_first_search_result_when_no_exact_match() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "assignee": ParsedJiraField(
                id="assignee",
                label="Assignee",
                required=False,
                type="user",
                searchable=True,
                options=[],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")

    with patch(
        "app.jira_create_service.search_assignable_users",
        AsyncMock(
            return_value=[
                {"label": "Test User", "value": "acc-test"},
                {"label": "Testing Admin", "value": "acc-admin"},
            ]
        ),
    ):
        resolved, missing = await resolve_agent_fields(
            config,
            metadata,
            {"assignee": "test"},
            project_id="10",
            project_key=None,
        )
    assert resolved["assignee"] == "acc-test"
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_assignee_clarification_when_no_search_results() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "assignee": ParsedJiraField(
                id="assignee",
                label="Assignee",
                required=False,
                type="user",
                searchable=True,
                options=[],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")

    with patch("app.jira_create_service.search_assignable_users", AsyncMock(return_value=[])):
        resolved, missing = await resolve_agent_fields(
            config,
            metadata,
            {"assignee": "xyz"},
            project_id="10",
            project_key=None,
        )
    assert "assignee" not in resolved
    assert len(missing) == 1
    assert missing[0].id == "assignee"
    assert "valid Assignee" in missing[0].question


@pytest.mark.asyncio
async def test_resolve_priority_exact_option() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "priority": ParsedJiraField(
                id="priority",
                label="Priority",
                required=False,
                type="priority",
                options=[
                    JiraFieldOption(label="High", value="2"),
                    JiraFieldOption(label="Low", value="1"),
                ],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    resolved, missing = await resolve_agent_fields(
        config,
        metadata,
        {"priority": "high"},
        project_id="10",
        project_key=None,
    )
    assert resolved["priority"] == "2"
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_labels_and_relative_start_date() -> None:
    from datetime import date, timedelta

    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "labels": ParsedJiraField(id="labels", label="Labels", required=False, type="labels"),
            "customfield_start": ParsedJiraField(
                id="customfield_start", label="Start date", required=False, type="date"
            ),
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    resolved, missing = await resolve_agent_fields(
        config,
        metadata,
        {"labels": "test and develop", "customfield_start": "5 days from today"},
        project_id="10",
        project_key=None,
    )
    assert resolved["labels"] == ["test", "develop"]
    assert resolved["customfield_start"] == (date.today() + timedelta(days=5)).isoformat()
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_active_sprint_option() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
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
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    resolved, missing = await resolve_agent_fields(
        config,
        metadata,
        {"customfield_sprint": "active sprint"},
        project_id="10",
        project_key=None,
    )
    assert resolved["customfield_sprint"] == "42"
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_due_date_next_week_friday() -> None:
    from datetime import date, timedelta

    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "duedate": ParsedJiraField(id="duedate", label="Due date", required=False, type="date"),
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    resolved, missing = await resolve_agent_fields(
        config,
        metadata,
        {"duedate": "due date next week friday"},
        project_id="10",
        project_key=None,
    )
    today = date.today()
    expected = (today + timedelta(days=(7 - today.weekday())) + timedelta(days=4)).isoformat()
    assert resolved["duedate"] == expected
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_parent_binds_when_key_in_metadata_options() -> None:
    from app.jira_create_models import JiraFieldOption

    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        project_key="SCRUM",
        fields={
            "parent": ParsedJiraField(
                id="parent",
                label="Parent",
                required=False,
                type="parent",
                searchable=True,
                options=[JiraFieldOption(label="SCRUM-5 — intended parent", value="SCRUM-5")],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")

    with (
        patch("app.jira_create_service.fetch_issue_id_for_key", AsyncMock(return_value="10005")),
        patch("app.jira_create_service.search_issues", AsyncMock()) as search,
    ):
        resolved, missing = await resolve_agent_fields(
            config,
            metadata,
            {"parent": "scrum 5"},
            project_id="10",
            project_key="SCRUM",
        )
    assert resolved["parent"] == "SCRUM-5"
    assert missing == []
    search.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_parent_rejects_key_not_in_metadata_options() -> None:
    from app.jira_create_models import JiraFieldOption, JiraIssueSearchOption

    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "parent": ParsedJiraField(
                id="parent",
                label="Parent",
                required=False,
                type="parent",
                searchable=True,
                options=[JiraFieldOption(label="SCRUM-21 — Hello Epic", value="SCRUM-21")],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")

    with patch(
        "app.jira_create_service.search_issues",
        AsyncMock(return_value=[JiraIssueSearchOption(label="SCRUM-7 — unrelated", value="SCRUM-7")]),
    ) as search:
        resolved, missing = await resolve_agent_fields(
            config,
            metadata,
            {"parent": "scrum 5"},
            project_id="10",
            project_key=None,
        )
    assert "parent" not in resolved
    assert len(missing) == 1
    assert missing[0].id == "parent"
    search.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_parent_exact_valid_key_match() -> None:
    from app.jira_create_models import JiraFieldOption

    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
            "parent": ParsedJiraField(
                id="parent",
                label="Parent",
                required=False,
                type="parent",
                searchable=True,
                options=[JiraFieldOption(label="SCRUM-21 — Hello Epic", value="SCRUM-21")],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    with patch("app.jira_create_service.fetch_issue_id_for_key", AsyncMock(return_value="10021")):
        resolved, missing = await resolve_agent_fields(
            config,
            metadata,
            {"parent": "SCRUM-21"},
            project_id="10",
            project_key="SCRUM",
        )
    assert resolved["parent"] == "SCRUM-21"
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_future_sprint_option() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="2",
        fields={
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
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    resolved, missing = await resolve_agent_fields(
        config,
        metadata,
        {"customfield_sprint": "future sprint"},
        project_id="10",
        project_key=None,
    )
    assert resolved["customfield_sprint"] == "99"
    assert missing == []


@pytest.mark.asyncio
async def test_resolve_linked_clone_scrum_8_adds_issue_link() -> None:
    from app.jira_create_agent_preprocess import LinkedWorkItemIntent
    from app.jira_create_agent_resolve import resolve_linked_work_items
    from app.jira_create_models import JiraIssueLinkTypeOption, JiraIssueSearchOption

    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    with (
        patch(
            "app.jira_create_service.list_issue_link_types",
            AsyncMock(
                return_value=[
                    JiraIssueLinkTypeOption(id="10000", name="Blocks", inward="is blocked by", outward="blocks"),
                    JiraIssueLinkTypeOption(id="10001", name="Cloners", inward="is cloned by", outward="clones"),
                ]
            ),
        ),
        patch(
            "app.jira_create_service.search_issues",
            AsyncMock(
                return_value=[
                    JiraIssueSearchOption(label="SCRUM-7 — unrelated", value="SCRUM-7"),
                    JiraIssueSearchOption(label="SCRUM-8 — source", value="SCRUM-8"),
                ]
            ),
        ),
    ):
        links, missing = await resolve_linked_work_items(
            config,
            [LinkedWorkItemIntent(relationship_intent="clone", target_intent="scrum 8")],
            project_id="10",
        )
    assert missing == []
    assert len(links) == 1
    assert links[0].link_type_id == "10001"
    assert links[0].target_issue_key == "SCRUM-8"
    assert links[0].new_issue_role == "outward"
