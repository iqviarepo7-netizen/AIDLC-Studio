from app.jira_create_models import JiraCreateMetadata, ParsedJiraField
from app.jira_create_validation import field_is_empty, merge_agent_fields, missing_required_fields
from app.jira_field_parser import normalize_jira_metadata, parse_jira_field, parse_select_options, sort_tabs
from app.jira_create_agent import validate_agent_payload


def test_number_schema_maps_to_number_type() -> None:
    field = parse_jira_field(
        "customfield_estimate",
        {"label": "Estimate", "schema": {"type": "number"}, "editHtml": '<input type="text" />'},
    )
    assert field.type == "number"


def test_parse_textarea_and_text_and_select() -> None:
    textarea = parse_jira_field("description", {"label": "Description", "required": True, "editHtml": "<textarea name='description'></textarea>"})
    text = parse_jira_field("summary", {"label": "Summary", "required": True, "editHtml": '<input type="text" name="summary" />'})
    select = parse_jira_field(
        "customfield_1",
        {
            "label": "Severity",
            "required": False,
            "editHtml": '<select><option value="">Choose</option><option value="27010">Cosmetic</option></select>',
        },
    )
    assert textarea.type == "textarea"
    assert text.type == "text"
    assert select.type == "select"
    assert select.options[1].label == "Cosmetic"
    assert select.options[1].value == "27010"


def test_parse_checkbox_radio_and_options() -> None:
    checkbox = parse_jira_field("customfield_multi", {"label": "Options", "editHtml": '<input type="checkbox" value="a">A</input>'})
    radio = parse_jira_field(
        "customfield_2",
        {"label": "Choice", "editHtml": '<input type="radio" value="1">One<input type="radio" value="2">Two'},
    )
    options = parse_select_options('<option value="x">&amp; Escaped</option><option disabled selected value="y">Default</option>')
    assert checkbox.type == "checkbox"
    assert radio.type == "radio"
    assert options[0].label == "& Escaped"
    assert options[1].disabled is True
    assert options[1].selected is True


def test_tab_sorting_and_field_order() -> None:
    raw = {
        "fields": {
            "summary": {"label": "Summary", "required": True, "editHtml": '<input type="text" />'},
            "description": {"label": "Description", "required": True, "editHtml": "<textarea></textarea>"},
        },
        "sortedTabs": [
            {"id": "b", "label": "B", "position": 2, "fields": ["description"]},
            {"id": "a", "label": "A", "position": 1, "fields": ["summary"]},
        ],
    }
    fields, tabs, _order = normalize_jira_metadata(raw, project_id="1", issue_type_id="2")
    assert [tab.label for tab in tabs] == ["A", "B"]
    assert tabs[0].fields == ["summary"]
    assert fields["summary"].tab == "a"


def test_unknown_tab_field_and_unsupported_html() -> None:
    raw = {
        "fields": {"summary": {"label": "Summary", "required": True, "editHtml": '<input type="text" />'}},
        "sortedTabs": [{"id": "t1", "label": "Details", "position": 0, "fields": ["summary", "missing"]}],
    }
    fields, tabs, _order = normalize_jira_metadata(raw, project_id="1", issue_type_id="2")
    assert "missing" not in fields
    assert tabs[0].fields == ["summary"]
    weird = parse_jira_field("weird", {"label": "Weird", "editHtml": "<script>alert(1)</script><div>noop</div>"})
    assert weird.type == "unsupported"


def test_tab_field_objects_resolve_to_ids() -> None:
    raw = {
        "fields": {
            "assignee": {"label": "Assignee", "required": False, "editHtml": '<input type="text" />'},
        },
        "sortedTabs": [
            {
                "id": "jira-tab-main",
                "label": "Details",
                "position": 0,
                "fields": [{"label": "Assignee", "id": "assignee"}, {"label": "Summary", "id": "summary"}],
            }
        ],
    }
    fields, tabs, _order = normalize_jira_metadata(raw, project_id="1", issue_type_id="2")
    assert tabs[0].fields == ["assignee"]
    assert tabs[0].label == "Details"
    assert fields["assignee"].label == "Assignee"


def test_issue_color_field_parsed_as_color_picker_with_swatches() -> None:
    color_field = parse_jira_field(
        "customfield_color",
        {
            "label": "Issue color",
            "required": False,
            "schema": {"type": "option", "custom": "com.pyxis.greenhopper.jira:gh-epic-color"},
            "allowedValues": [
                {"id": "10001", "value": "teal", "name": "Teal", "color": "#00B8D9"},
                {"id": "10002", "value": "purple", "name": "Purple", "color": "#8777D9"},
            ],
            "hasDefaultValue": True,
            "defaultValue": {"id": "10001", "name": "Teal"},
        },
    )
    assert color_field.type == "color-picker"
    assert color_field.options[0].label == "Teal"
    assert color_field.options[0].swatch_color == "#00B8D9"
    assert color_field.default_value == "10001"


def test_status_field_parsed_as_select_with_jira_options() -> None:
    status = parse_jira_field(
        "status",
        {
            "label": "Status",
            "required": False,
            "editable": True,
            "schema": {"type": "status", "system": "status"},
            "allowedValues": [
                {"id": "1", "name": "To Do"},
                {"id": "2", "name": "In Progress"},
            ],
            "hasDefaultValue": True,
            "defaultValue": {"id": "1", "name": "To Do"},
        },
    )
    assert status.type == "status"

    readonly_status = parse_jira_field(
        "status",
        {
            "label": "Status",
            "required": False,
            "schema": {"type": "status", "system": "status"},
            "allowedValues": [{"id": "1", "name": "To Do"}],
        },
    )
    assert readonly_status.type == "readonly"
    assert [option.label for option in status.options] == ["To Do", "In Progress"]
    assert status.default_value == "1"


def test_required_blocking_and_agent_validation() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
        },
        sorted_tabs=sort_tabs([{"id": "d", "label": "Details", "position": 0, "fields": ["summary", "description"]}]),
    )
    missing = missing_required_fields(metadata, {"summary": "A title"})
    assert len(missing) == 1
    assert missing[0].id == "description"
    assert field_is_empty("  ") is True

    validated = validate_agent_payload(
        {
            "status": "ready",
            "message": "done",
            "fields": {"summary": "Title", "description": "Body", "unknown": "x"},
            "missingRequiredFields": [],
        },
        metadata,
    )
    assert "unknown" not in validated.fields
    assert validated.fields["summary"] == "Title"


def test_merge_preserves_user_edited_values() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
        },
        sorted_tabs=[],
    )
    merged = merge_agent_fields(
        metadata,
        {"summary": "Human title", "description": ""},
        {"summary": "Agent title", "description": "Agent body"},
        {"summary"},
    )
    assert merged["summary"] == "Human title"
    assert merged["description"] == "Agent body"


def test_sprint_field_prefers_allowed_values_over_placeholder_edit_html() -> None:
    sprint = parse_jira_field(
        "customfield_10020",
        {
            "label": "Sprint",
            "required": False,
            "schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"},
            "editHtml": '<select><option value="">Select sprint</option></select>',
            "allowedValues": [
                {"id": 42, "name": "SCRUM Sprint 0", "state": "active"},
                {"id": 43, "name": "SCRUM Sprint 1", "state": "future"},
            ],
        },
    )
    assert sprint.type == "select"
    assert len(sprint.options) == 2
    assert sprint.options[0].value == "42"
    assert "Sprint 0" in sprint.options[0].label
