from app.jira_create_metadata_policy import apply_create_jira_field_policy
from app.jira_create_models import JiraTabDefinition, ParsedJiraField


def _field(field_id: str, *, label: str | None = None, required: bool = False) -> ParsedJiraField:
    return ParsedJiraField(id=field_id, label=label or field_id, required=required, type="text")


def test_reporter_override_then_filtered_out() -> None:
    fields = {
        "summary": _field("summary", label="Summary", required=True),
        "reporter": _field("reporter", label="Reporter", required=True),
    }
    filtered, tabs = apply_create_jira_field_policy(fields, [])
    assert "reporter" not in filtered
    assert filtered["summary"].required is True


def test_description_override_then_kept() -> None:
    fields = {
        "summary": _field("summary", label="Summary", required=True),
        "description": _field("description", label="Description", required=False),
    }
    filtered, _tabs = apply_create_jira_field_policy(fields, [])
    assert "description" in filtered
    assert filtered["description"].required is True


def test_optional_assignee_removed() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "assignee": _field("assignee", label="Assignee", required=False),
    }
    filtered, _tabs = apply_create_jira_field_policy(fields, [])
    assert "assignee" not in filtered


def test_dynamic_custom_required_field_kept() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "customfield_99999": _field("customfield_99999", label="Client Name", required=True),
    }
    filtered, _tabs = apply_create_jira_field_policy(fields, [])
    assert "customfield_99999" in filtered


def test_dynamic_custom_optional_field_removed() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "customfield_99999": _field("customfield_99999", label="Client Name", required=False),
    }
    filtered, _tabs = apply_create_jira_field_policy(fields, [])
    assert "customfield_99999" not in filtered


def test_tab_field_references_synchronized() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "description": _field("description", required=False),
        "reporter": _field("reporter", required=True),
        "assignee": _field("assignee", required=False),
    }
    tabs = [
        JiraTabDefinition(
            id="jira-tab-main",
            label="Details",
            position=0,
            fields=["summary", "description", "reporter", "assignee"],
        )
    ]
    filtered, synced = apply_create_jira_field_policy(fields, tabs)
    assert synced[0].fields == ["summary", "description"]
    assert set(filtered.keys()) == {"summary", "description"}


def test_empty_tab_removed_after_filtering() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "priority": _field("priority", required=False),
        "assignee": _field("assignee", required=False),
    }
    tabs = [
        JiraTabDefinition(id="main", label="Details", position=0, fields=["summary"]),
        JiraTabDefinition(id="hf", label="HF Details", position=1, fields=["priority", "assignee"]),
    ]
    _filtered, synced = apply_create_jira_field_policy(fields, tabs)
    assert len(synced) == 1
    assert synced[0].id == "main"


def test_description_override_before_filter() -> None:
    fields = {"description": _field("description", required=False)}
    filtered, _tabs = apply_create_jira_field_policy(fields, [])
    assert "description" in filtered


def test_reporter_override_before_filter() -> None:
    fields = {"reporter": _field("reporter", required=True)}
    filtered, _tabs = apply_create_jira_field_policy(fields, [])
    assert "reporter" not in filtered


def test_solitary_general_tab_flattened() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "description": _field("description", required=False),
    }
    tabs = [JiraTabDefinition(id="panel-1", label="General", position=0, fields=["summary", "description"])]
    _filtered, synced = apply_create_jira_field_policy(fields, tabs)
    assert synced == []
