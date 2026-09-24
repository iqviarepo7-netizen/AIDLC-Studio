from unittest.mock import AsyncMock, patch

import pytest

from app.connection_models import JiraConnectionConfig
from app.jira_create_models import JiraCreateMetadata, ParsedJiraField
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
