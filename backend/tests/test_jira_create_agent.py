from app.jira_create_agent import enforce_mandatory_fields
from app.jira_create_models import CreateJiraAgentRequest, CreateJiraAgentResponse, JiraCreateMetadata, ParsedJiraField


def test_agent_cannot_bypass_mandatory_fields() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "customfield_client": ParsedJiraField(id="customfield_client", label="Client Name", required=True, type="text"),
        },
        sorted_tabs=[],
    )
    response = CreateJiraAgentResponse(
        status="ready",
        message="All set",
        fields={"summary": "Saved value missing on edit screen"},
        missing_required_fields=[],
    )
    request = CreateJiraAgentRequest(
        messages=[],
        project_id="1",
        issue_type_id="2",
        project_label="MK (SCRUM)",
        issue_type_label="Task",
        current_values=response.fields,
    )
    enforced = enforce_mandatory_fields(metadata, request, response, response.fields)
    assert enforced.status == "needs_information"
    assert any(item.id == "customfield_client" for item in enforced.missing_required_fields)
    assert "Reporter" not in enforced.message or "customfield_client" in enforced.message
    assert "I need more details" not in enforced.message.lower()
    assert "customfield_client" in enforced.message or "Client Name" in enforced.message
