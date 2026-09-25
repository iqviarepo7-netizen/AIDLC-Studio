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
from app.jira_create_service import (
    canonicalize_jira_issue_key,
    match_jira_issue_key,
    match_jira_search_option,
    normalize_jira_compare_text,
    resolve_assignable_user_value,
)
from app.jira_create_agent_resolve import resolve_agent_fields


def test_normalize_jira_compare_text_collapses_whitespace_and_case() -> None:
    assert normalize_jira_compare_text("  MOHAN   IMPELOX ") == normalize_jira_compare_text("Mohan impelox")


def test_match_jira_search_option_exact_display_name() -> None:
    items = [
        {"label": "Mohan impelox", "value": "acc-mohan"},
        {"label": "IQVIA Test", "value": "acc-test"},
    ]
    value, _ = match_jira_search_option("Mohan impelox", items)
    assert value == "acc-mohan"


def test_match_jira_search_option_case_insensitive_exact() -> None:
    items = [{"label": "Mohan impelox", "value": "acc-mohan"}]
    value, _ = match_jira_search_option("MOHAN IMPELOX", items)
    assert value == "acc-mohan"


def test_match_jira_search_option_first_result_fallback() -> None:
    items = [
        {"label": "Mohan impelox", "value": "acc-mohan"},
        {"label": "IQVIA Test", "value": "acc-test"},
    ]
    value, _ = match_jira_search_option("mohan", items)
    assert value == "acc-mohan"


def test_match_jira_search_option_empty_results() -> None:
    value, labels = match_jira_search_option("unknown-user-xyz", [])
    assert value is None
    assert labels == []


def test_canonicalize_jira_issue_key_normalizes_spaces_and_case() -> None:
    assert canonicalize_jira_issue_key("scrum 5") == "SCRUM-5"
    assert canonicalize_jira_issue_key("scrum-5") == "SCRUM-5"
    assert canonicalize_jira_issue_key("SCRUM 5") == "SCRUM-5"
    assert canonicalize_jira_issue_key("SCRUM-5") == "SCRUM-5"


def test_match_jira_issue_key_exact_normalized_match_not_first_result() -> None:
    items = [
        {"label": "SCRUM-7 — unrelated", "value": "SCRUM-7"},
        {"label": "SCRUM-5 — intended", "value": "SCRUM-5"},
    ]
    value, _ = match_jira_issue_key("scrum 5", items)
    assert value == "SCRUM-5"


def test_match_jira_issue_key_does_not_fall_back_to_first_result() -> None:
    items = [{"label": "SCRUM-7 — unrelated", "value": "SCRUM-7"}]
    value, labels = match_jira_issue_key("scrum 5", items)
    assert value is None
    assert "SCRUM-7 — unrelated" in labels


@pytest.mark.asyncio
async def test_resolve_assignable_user_value_uses_search_results() -> None:
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    with patch(
        "app.jira_create_service.search_assignable_users",
        AsyncMock(
            return_value=[
                {"label": "Mohan impelox", "value": "557058:aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
                {"label": "IQVIA Test", "value": "557058:ffff-gggg-hhhh-iiii-jjjjjjjjjjjj"},
            ]
        ),
    ):
        value, labels = await resolve_assignable_user_value(
            config,
            project_key="SCRUM",
            project_id="10",
            raw="Mohan impelox",
        )
    assert value == "557058:aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert "Mohan impelox" in labels


@pytest.mark.asyncio
async def test_resolve_agent_fields_skips_display_name_option_and_uses_search() -> None:
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
                options=[JiraFieldOption(label="Mohan impelox", value="Mohan impelox")],
            )
        },
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    with patch(
        "app.jira_create_service.resolve_assignable_user_value",
        AsyncMock(return_value=("557058:aaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ["Mohan impelox"])),
    ):
        resolved, missing = await resolve_agent_fields(
            config,
            metadata,
            {"assignee": "Mohan impelox"},
            project_id="10",
            project_key="SCRUM",
        )
    assert resolved["assignee"] == "557058:aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert missing == []


@pytest.mark.asyncio
async def test_pending_assignee_reply_mohan_impelox_preserves_summary() -> None:
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
            CreateJiraAgentMessage(role="user", content="initial"),
            CreateJiraAgentMessage(role="assistant", content="Please provide Assignee"),
            CreateJiraAgentMessage(role="user", content="Mohan impelox"),
        ],
        project_id="10",
        issue_type_id="2",
        current_values={
            "summary": "Add welcome popup",
            "description": "Solution:\nShow popup.\n\nAcceptance Criteria:\nPopup appears.",
        },
        conversation_phase="field_resolution",
        pending_fields=[PendingAgentField(field_id="assignee", requested_value="mohan")],
        pending_clarification_field_id="assignee",
    )
    with patch(
        "app.jira_create_service.search_assignable_users",
        AsyncMock(
            return_value=[
                {"label": "Mohan impelox", "value": "557058:aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
                {"label": "IQVIA Test", "value": "557058:ffff-gggg-hhhh-iiii-jjjjjjjjjjjj"},
            ]
        ),
    ):
        response = await analyze_requirement(provider, metadata, request, config)

    provider.generate.assert_not_called()
    assert response.fields["assignee"] == "557058:aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert response.fields["summary"] == "Add welcome popup"
    assert response.conversation_phase == "ready_to_create"
