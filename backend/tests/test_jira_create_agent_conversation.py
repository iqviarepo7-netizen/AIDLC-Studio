from app.jira_create_agent_conversation import (
    infer_conversation_phase,
    interpret_field_resolution_reply,
    is_requirement_modification,
    parse_field_change_command,
)
from app.jira_create_models import (
    CreateJiraAgentMessage,
    CreateJiraAgentRequest,
    JiraCreateMetadata,
    JiraFieldOption,
    ParsedJiraField,
    PendingAgentField,
)


def test_infer_field_resolution_after_initial_summary_description() -> None:
    request = CreateJiraAgentRequest(
        messages=[
            CreateJiraAgentMessage(role="user", content="add popup"),
            CreateJiraAgentMessage(role="assistant", content="need assignee"),
            CreateJiraAgentMessage(role="user", content="navi"),
        ],
        project_id="1",
        issue_type_id="2",
        current_values={"summary": "Popup", "description": "Solution:\nx\n\nAcceptance Criteria:\ny"},
    )
    assert infer_conversation_phase(request) == "field_resolution"


def test_interpret_sprint_option_reply() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "customfield_sprint": ParsedJiraField(
                id="customfield_sprint",
                label="Sprint",
                required=False,
                type="select",
                options=[JiraFieldOption(label="Active: SCRUM Sprint 0", value="42")],
            ),
            "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user"),
        },
        sorted_tabs=[],
    )
    updates = interpret_field_resolution_reply(
        "Active: SCRUM Sprint 0",
        metadata,
        pending_fields=[
            PendingAgentField(field_id="customfield_sprint"),
            PendingAgentField(field_id="assignee"),
        ],
        pending_clarification_field_id=None,
    )
    assert updates == {"customfield_sprint": "Active: SCRUM Sprint 0"}


def test_parse_field_change_command_without_requirement_regeneration() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "priority": ParsedJiraField(
                id="priority",
                label="Priority",
                required=False,
                type="priority",
                options=[JiraFieldOption(label="High", value="2")],
            )
        },
        sorted_tabs=[],
    )
    assert parse_field_change_command("change priority to High", metadata) == {"priority": "High"}
    assert is_requirement_modification("change priority to High") is False


def test_requirement_modification_detects_new_functionality() -> None:
    assert is_requirement_modification("also make the popup close automatically after 5 seconds") is True
