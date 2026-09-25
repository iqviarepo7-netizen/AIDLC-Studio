from app.jira_create_agent import (
    enforce_mandatory_fields,
    format_structured_description,
    parse_agent_llm_payload,
    select_pending_clarification_field,
)
from app.jira_create_models import CreateJiraAgentRequest, CreateJiraAgentResponse, JiraCreateMetadata, MissingRequiredField, ParsedJiraField


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


def test_parse_agent_llm_payload_structured_description_and_field_labels() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
            "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user"),
            "customfield_start": ParsedJiraField(
                id="customfield_start", label="Start date", required=False, type="date"
            ),
        },
        sorted_tabs=[],
    )
    payload = {
        "summary": "Add welcome popup to Run Pipeline action",
        "description": {
            "solution": "When the user clicks Run Pipeline, display a popup containing the message 'Welcome home'.",
            "acceptanceCriteria": "Clicking Run Pipeline displays the popup with the expected message.",
        },
        "fields": {
            "assignee": "mohan",
            "start date": "5 days from today",
        },
    }
    parsed = parse_agent_llm_payload(payload, metadata)
    description = parsed["fields"]["description"]
    assert "Solution:" in description
    assert "Acceptance Criteria:" in description
    assert "mohan" not in description.lower()
    assert parsed["fields"]["assignee"] == "mohan"
    assert parsed["fields"]["customfield_start"] == "5 days from today"


def test_format_structured_description_rejects_jira_metadata_in_sections() -> None:
    text = format_structured_description(
        {
            "solution": "Show a welcome popup when Run Pipeline is clicked.",
            "acceptanceCriteria": (
                "Popup text is visible and pipeline still runs.\n"
                "• Story points are set to 5.\n"
                "• Assignee is IQVIA.\n"
                "• Labels test and develop are applied.\n"
                "• Issue is linked as a clone of scrum 8."
            ),
        }
    )
    assert text is not None
    lowered = text.lower()
    assert "assignee" not in lowered
    assert "priority" not in lowered
    assert "story point" not in lowered
    assert "labels" not in lowered
    assert "clone" not in lowered
    assert "solution:" in lowered
    assert "acceptance criteria:" in lowered
    assert "welcome popup" in lowered or "run pipeline" in lowered


def test_select_pending_clarification_field_prefers_single_resolution_failure() -> None:
    missing = [
        MissingRequiredField(
            id="assignee",
            label="Assignee",
            question="I couldn't find a Assignee matching 'xyz'. Please provide a valid Assignee.",
        )
    ]
    assert select_pending_clarification_field(missing) == "assignee"
