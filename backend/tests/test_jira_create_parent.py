import pytest

from app.connection_models import JiraConnectionConfig
from app.jira_create_models import JiraCreateMetadata, JiraIssueSearchOption, ParsedJiraField
from app.jira_create_service import _enrich_parent_fields, build_parent_candidate_jql
from app.jira_field_parser import options_from_parent_allowed_values, parse_jira_field


def test_parent_allowed_values_use_issue_keys() -> None:
    options = options_from_parent_allowed_values(
        {
            "allowedValues": [
                {"id": "10021", "key": "SCRUM-21", "name": "Hello Epic"},
            ]
        }
    )
    assert len(options) == 1
    assert options[0].value == "SCRUM-21"
    assert "Hello Epic" in options[0].label


def test_parse_parent_field_prefers_create_metadata_allowed_values() -> None:
    field = parse_jira_field(
        "parent",
        {
            "label": "Parent",
            "schema": {"type": "issuelink", "system": "parent"},
            "allowedValues": [
                {"id": "10021", "key": "SCRUM-21", "name": "Hello Epic"},
            ],
            "editHtml": "<input type='text' />",
        },
    )
    assert field.type == "parent"
    assert len(field.options) == 1
    assert field.options[0].value == "SCRUM-21"


@pytest.mark.asyncio
async def test_enrich_parent_fields_backfills_options_from_raw_field() -> None:
    fields = {
        "parent": ParsedJiraField(
            id="parent",
            label="Parent",
            required=False,
            type="parent",
            searchable=True,
            options=[],
            raw_field={
                "allowedValues": [{"id": "10021", "key": "SCRUM-21", "name": "Hello Epic"}],
            },
        )
    }
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    await _enrich_parent_fields(
        config,
        fields,
        project_key="SCRUM",
        project_id="10",
        issue_type_id="2",
    )
    assert fields["parent"].options[0].value == "SCRUM-21"


@pytest.mark.asyncio
async def test_build_parent_candidate_jql_uses_hierarchy_levels() -> None:
    from unittest.mock import AsyncMock, patch

    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    issue_types = [
        {"id": "10004", "name": "Story", "hierarchyLevel": 0, "subtask": False},
        {"id": "10001", "name": "Epic", "hierarchyLevel": 1, "subtask": False},
        {"id": "10002", "name": "Subtask", "hierarchyLevel": -1, "subtask": True},
    ]
    with patch("app.jira_create_service.fetch_project_issue_types", AsyncMock(return_value=issue_types)):
        jql = await build_parent_candidate_jql(
            config,
            project_id="10000",
            project_key="SCRUM",
            issue_type_id="10004",
        )
    assert jql == 'project = "SCRUM" AND issuetype in (10001)'


def test_generic_issue_search_option_not_in_parent_metadata() -> None:
    """Parent eligibility comes from create metadata, not issue picker results."""
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
                options=[parse_jira_field("parent", {"allowedValues": [{"key": "SCRUM-21", "name": "Epic"}]}).options[0]],
            )
        },
        sorted_tabs=[],
    )
    parent = metadata.fields["parent"]
    assert all(option.value != "SCRUM-7" for option in parent.options)
    assert parent.options[0].value == "SCRUM-21"
