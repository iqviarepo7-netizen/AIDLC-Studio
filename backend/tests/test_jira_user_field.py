from app.jira_create_models import JiraCreateMetadata, ParsedJiraField
from app.jira_create_service import build_jira_fields_payload
from app.jira_user_field import is_automatic_or_empty_user_value


def test_automatic_assignee_tokens_are_not_submittable() -> None:
    assert is_automatic_or_empty_user_value("-1") is True
    assert is_automatic_or_empty_user_value("automatic") is True
    assert is_automatic_or_empty_user_value("Automatic") is True
    assert is_automatic_or_empty_user_value("") is True
    assert is_automatic_or_empty_user_value("  ") is True
    assert is_automatic_or_empty_user_value("557058:abc-def-ghi") is False


def test_assignee_omitted_from_payload_for_automatic_values() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={"assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user")},
        sorted_tabs=[],
    )
    for automatic in ("-1", "automatic", "unassigned"):
        payload = build_jira_fields_payload(metadata, {"assignee": automatic}, api_version="2")
        assert "assignee" not in payload

    payload = build_jira_fields_payload(
        metadata,
        {"assignee": "557058:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
        api_version="2",
    )
    assert payload["assignee"] == {"accountId": "557058:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
