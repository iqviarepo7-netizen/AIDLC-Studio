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
    enforced = enforce_mandatory_fields(metadata, request, response, response.fields, requirement="")
    assert enforced.status == "needs_information"
    assert any(item.id == "customfield_client" for item in enforced.missing_required_fields)
    assert "Reporter" not in enforced.message or "customfield_client" in enforced.message
    assert "I need more details" not in enforced.message.lower()
    assert "customfield_client" in enforced.message or "Client Name" in enforced.message


def test_agent_skips_summary_description_prompts_when_requirement_exists() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
            "customfield_client": ParsedJiraField(id="customfield_client", label="Client Name", required=True, type="text"),
        },
        sorted_tabs=[],
    )
    response = CreateJiraAgentResponse(status="ready", message="", fields={}, missing_required_fields=[])
    request = CreateJiraAgentRequest(messages=[], project_id="1", issue_type_id="2", current_values={})
    enforced = enforce_mandatory_fields(
        metadata,
        request,
        response,
        {},
        requirement="Add popup when pipeline runs.",
    )
    assert enforced.status == "needs_information"
    assert all(item.id not in {"summary", "description"} for item in enforced.missing_required_fields)
    assert any(item.id == "customfield_client" for item in enforced.missing_required_fields)
