from app.jira_create_models import JiraCreateMetadata, JiraFieldOption, ParsedJiraField
from app.jira_create_service import build_jira_fields_payload
from app.jira_create_validation import normalize_create_field_values
from app.jira_field_parser import parse_jira_field, status_submittable_on_create


def test_normalize_summary_trim() -> None:
    values = normalize_create_field_values({"summary": "  Title  "})
    assert values["summary"] == "Title"


def test_number_schema_parsed_and_serialized_as_json_number() -> None:
    field = parse_jira_field(
        "customfield_points",
        {
            "label": "Estimate",
            "required": False,
            "schema": {"type": "number", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:float"},
            "editHtml": '<input type="text" />',
        },
    )
    assert field.type == "number"
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={field.id: field},
        sorted_tabs=[],
    )
    payload = build_jira_fields_payload(metadata, {field.id: "3"}, api_version="2")
    assert payload[field.id] == 3
    assert isinstance(payload[field.id], int)


def test_status_not_submitted_when_not_editable() -> None:
    status_field = parse_jira_field(
        "status",
        {
            "label": "Status",
            "required": False,
            "editable": False,
            "schema": {"type": "status", "system": "status"},
            "allowedValues": [{"id": "1", "name": "To Do"}],
            "editHtml": "<select><option value='1'>To Do</option></select>",
        },
    )
    assert status_field.type == "readonly"
    assert status_submittable_on_create({"editable": False, "allowedValues": [{"id": "1"}]}) is False
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={"status": status_field},
        sorted_tabs=[],
    )
    payload = build_jira_fields_payload(metadata, {"status": "1"}, api_version="2")
    assert "status" not in payload


def test_custom_dynamic_select_field_still_maps_to_option_id() -> None:
    metadata = JiraCreateMetadata(
        project_id="10",
        issue_type_id="20",
        fields={
            "customfield_team": ParsedJiraField(
                id="customfield_team",
                label="Team",
                required=False,
                type="select",
                options=[JiraFieldOption(label="Alpha", value="42")],
            ),
        },
        sorted_tabs=[],
    )
    payload = build_jira_fields_payload(metadata, {"customfield_team": "42"}, api_version="2")
    assert payload["customfield_team"] == {"id": "42"}


def test_generic_field_contracts_in_payload() -> None:
    fields = {
        "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
        "labels": ParsedJiraField(id="labels", label="Labels", required=False, type="labels"),
        "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user"),
        "priority": ParsedJiraField(
            id="priority",
            label="Priority",
            required=False,
            type="priority",
            options=[JiraFieldOption(label="Medium", value="3")],
        ),
        "parent": ParsedJiraField(id="parent", label="Parent", required=False, type="parent", searchable=True),
        "customfield_flag": ParsedJiraField(
            id="customfield_flag",
            label="Flag",
            required=False,
            type="checkbox",
            options=[JiraFieldOption(label="Impediment", value="100")],
        ),
    }
    metadata = JiraCreateMetadata(project_id="10", issue_type_id="20", fields=fields, sorted_tabs=[])
    payload = build_jira_fields_payload(
        metadata,
        {
            "summary": "Hello",
            "labels": ["a", "b"],
            "assignee": "account-abc-123456789012345678",
            "priority": "3",
            "parent": "SCRUM-1",
            "customfield_flag": ["100"],
        },
        api_version="2",
    )
    assert payload["summary"] == "Hello"
    assert payload["labels"] == ["a", "b"]
    assert payload["assignee"] == {"accountId": "account-abc-123456789012345678"}
    assert payload["priority"] == {"id": "3"}
    assert payload["parent"] == {"key": "SCRUM-1"}
    assert payload["customfield_flag"] == [{"id": "100"}]
