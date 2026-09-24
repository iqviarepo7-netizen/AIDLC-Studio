import pytest
from unittest.mock import AsyncMock, patch

from app.connection_models import JiraConnectionConfig
from app.jira_create_models import ParsedJiraField, JiraIssueSearchOption
from app.jira_create_service import search_parent_issues


@pytest.mark.asyncio
async def test_search_parent_issues_filters_generic_picker_with_hierarchy_jql() -> None:
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    field = ParsedJiraField(id="parent", label="Parent", required=False, type="parent", searchable=True, options=[])

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "sections": [
                    {
                        "issues": [
                            {"key": "SCRUM-21", "summaryText": "Hello Epic"},
                            {"key": "SCRUM-5", "summaryText": "Story"},
                        ]
                    }
                ]
            }

    with (
        patch(
            "app.jira_create_service.build_parent_candidate_jql",
            AsyncMock(return_value='project = "SCRUM" AND issuetype in (10001)'),
        ),
        patch("app.integrations.direct_jira._request", AsyncMock(return_value=FakeResponse())) as request,
    ):
        issues = await search_parent_issues(
            config,
            project_id="10000",
            project_key="SCRUM",
            issue_type_id="10004",
            field=field,
            query="",
        )

    assert [issue.value for issue in issues] == ["SCRUM-21", "SCRUM-5"]
    assert request.await_args.kwargs["params"]["currentJQL"] == 'project = "SCRUM" AND issuetype in (10001)'


@pytest.mark.asyncio
async def test_search_parent_issues_falls_back_to_jql_when_picker_empty() -> None:
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")
    field = ParsedJiraField(id="parent", label="Parent", required=False, type="parent", searchable=True, options=[])

    class EmptyPickerResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"sections": []}

    class JqlSearchResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "issues": [
                    {"id": "10021", "key": "SCRUM-21", "fields": {"summary": "Hello Epic"}},
                    {"id": "10022", "key": "SCRUM-22", "fields": {"summary": "Hi Epic parent JIRA"}},
                ]
            }

    request_mock = AsyncMock(side_effect=[EmptyPickerResponse(), EmptyPickerResponse(), JqlSearchResponse()])

    with (
        patch(
            "app.jira_create_service._parent_search_jql_candidates",
            AsyncMock(return_value=['project = "SCRUM" AND issuetype in (10001)']),
        ),
        patch("app.integrations.direct_jira._request", request_mock),
    ):
        issues = await search_parent_issues(
            config,
            project_id="10000",
            project_key="SCRUM",
            issue_type_id="10004",
            field=field,
            query="",
        )

    assert [issue.value for issue in issues] == ["SCRUM-21", "SCRUM-22"]
    assert request_mock.await_count == 3
    jql_calls = [call for call in request_mock.await_args_list if len(call.args) > 2 and call.args[2] == "/search/jql"]
    assert len(jql_calls) == 1
    assert jql_calls[0].args[1] == "POST"


@pytest.mark.asyncio
async def test_search_create_parent_issues_uses_metadata_parent_field() -> None:
    from app.jira_create_models import JiraCreateMetadata, JiraFieldOption
    from app.jira_create_service import search_create_parent_issues

    parent = ParsedJiraField(
        id="parent",
        label="Parent",
        required=False,
        type="parent",
        searchable=True,
        options=[
            JiraFieldOption(label="SCRUM-22 — Hi Epic parent JIRA", value="SCRUM-22"),
            JiraFieldOption(label="SCRUM-21 — Hello Epic", value="SCRUM-21"),
        ],
    )
    metadata = JiraCreateMetadata(
        project_id="10000",
        issue_type_id="10004",
        project_key="SCRUM",
        fields={"parent": parent},
        sorted_tabs=[],
    )
    config = JiraConnectionConfig(mode="direct", base_url="https://jira.example.com", email="u@x.com", api_token="t")

    with (
        patch("app.jira_create_service.require_direct_jira", return_value=config),
        patch(
            "app.jira_create_service._load_parent_field_for_search",
            AsyncMock(return_value=(parent, "SCRUM")),
        ),
        patch(
            "app.jira_create_service.search_parent_issues",
            AsyncMock(return_value=[JiraIssueSearchOption(label="SCRUM-21 — Hello Epic", value="SCRUM-21")]),
        ) as search,
    ):
        issues = await search_create_parent_issues(
            object(),
            project_id="10000",
            issue_type_id="10004",
            query="hello",
        )

    assert len(issues) == 1
    search.assert_awaited_once()
    assert search.await_args.kwargs["field"] is parent
    assert search.await_args.kwargs["project_key"] == "SCRUM"
    assert search.await_args.kwargs["query"] == "hello"
