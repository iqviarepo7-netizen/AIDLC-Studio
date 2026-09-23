from app.jira_create_models import JiraCreateMetadata, ParsedJiraField
from app.jira_create_validation import field_is_empty, merge_agent_fields, missing_required_fields
from app.jira_field_parser import normalize_jira_metadata, parse_jira_field, parse_select_options, sort_tabs
from app.jira_create_agent import validate_agent_payload


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
    checkbox = parse_jira_field("labels", {"label": "Labels", "editHtml": '<input type="checkbox" value="a">A</input>'})
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
    fields, tabs = normalize_jira_metadata(raw, project_id="1", issue_type_id="2")
    assert [tab.label for tab in tabs] == ["A", "B"]
    assert tabs[0].fields == ["summary"]
    assert fields["summary"].tab == "a"


def test_unknown_tab_field_and_unsupported_html() -> None:
    raw = {
        "fields": {"summary": {"label": "Summary", "required": True, "editHtml": '<input type="text" />'}},
        "sortedTabs": [{"id": "t1", "label": "Details", "position": 0, "fields": ["summary", "missing"]}],
    }
    fields, tabs = normalize_jira_metadata(raw, project_id="1", issue_type_id="2")
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
    fields, tabs = normalize_jira_metadata(raw, project_id="1", issue_type_id="2")
    assert tabs[0].fields == ["assignee"]
    assert tabs[0].label == "Details"
    assert fields["assignee"].label == "Assignee"


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
