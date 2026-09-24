from app.connection_models import JiraConnectionConfig
from app.jira_create_service import _assignable_user_search_param_sets


def test_assignable_search_v3_uses_query_not_username() -> None:
    config = JiraConnectionConfig(
        mode="direct",
        base_url="https://jira.example.com",
        email="u@example.com",
        api_token="token",
        api_version="3",
    )
    params = _assignable_user_search_param_sets(
        config,
        project_key="SCRUM",
        project_id="10",
        query="mohan",
        max_results=20,
    )[0]
    assert params["query"] == "mohan"
    assert "username" not in params
    assert params["project"] == "SCRUM"


def test_assignable_search_v2_uses_username() -> None:
    config = JiraConnectionConfig(
        mode="direct",
        base_url="https://jira.example.com",
        email="u@example.com",
        api_token="token",
        api_version="2",
    )
    params = _assignable_user_search_param_sets(
        config,
        project_key=None,
        project_id="10",
        query="mohan",
        max_results=20,
    )[0]
    assert params["username"] == "mohan"
    assert params["projectId"] == "10"
