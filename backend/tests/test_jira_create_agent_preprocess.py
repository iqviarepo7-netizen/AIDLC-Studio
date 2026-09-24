from app.jira_create_models import JiraCreateMetadata, ParsedJiraField
from app.jira_create_agent_preprocess import preprocess_user_message


def test_preprocess_splits_requirement_and_assignee() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user", searchable=True),
        },
        sorted_tabs=[],
    )
    text = (
        "add a popup when user clicks on run pipeline button. "
        "popup contains pipeline is running. assign as mohan."
    )
    result = preprocess_user_message(text, metadata)
    assert "assign" not in result.requirement.lower() or "mohan" not in result.requirement.lower()
    assert result.provided_fields.get("assignee", "").lower().startswith("mohan")


def test_preprocess_does_not_invent_unknown_fields() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={"summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text")},
        sorted_tabs=[],
    )
    result = preprocess_user_message("fix login bug assign as mohan", metadata)
    assert "mohan" not in result.provided_fields
