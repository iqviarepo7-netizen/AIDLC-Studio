from app.jira_create_metadata_policy import apply_create_jira_field_policy
from app.jira_create_models import JiraTabDefinition, ParsedJiraField


def _field(field_id: str, *, label: str | None = None, required: bool = False) -> ParsedJiraField:
    return ParsedJiraField(id=field_id, label=label or field_id, required=required, type="text")


def test_reporter_override_still_on_form() -> None:
    fields = {
        "summary": _field("summary", label="Summary", required=True),
        "reporter": _field("reporter", label="Reporter", required=True),
    }
    filtered, tabs, required_ids, _order = apply_create_jira_field_policy(fields, [])
    assert "reporter" in filtered
    assert filtered["reporter"].required is False
    assert "reporter" not in required_ids
    assert filtered["summary"].required is True


def test_description_override_then_kept() -> None:
    fields = {
        "summary": _field("summary", label="Summary", required=True),
        "description": _field("description", label="Description", required=False),
    }
    filtered, _tabs, required_ids, _order = apply_create_jira_field_policy(fields, [])
    assert "description" in filtered
    assert filtered["description"].required is True
    assert "description" in required_ids


def test_optional_assignee_kept_on_form() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "assignee": _field("assignee", label="Assignee", required=False),
    }
    filtered, _tabs, required_ids, _order = apply_create_jira_field_policy(fields, [])
    assert "assignee" in filtered
    assert "assignee" not in required_ids


def test_dynamic_custom_required_field_kept() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "customfield_99999": _field("customfield_99999", label="Client Name", required=True),
    }
    filtered, _tabs, required_ids, _order = apply_create_jira_field_policy(fields, [])
    assert "customfield_99999" in filtered
    assert "customfield_99999" in required_ids


def test_dynamic_custom_optional_field_kept() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "customfield_99999": _field("customfield_99999", label="Client Name", required=False),
    }
    filtered, _tabs, required_ids, _order = apply_create_jira_field_policy(fields, [])
    assert "customfield_99999" in filtered
    assert "customfield_99999" not in required_ids


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
    filtered, synced, _required_ids, _order = apply_create_jira_field_policy(fields, tabs)
    assert synced[0].fields == ["summary", "description", "reporter", "assignee"]
    assert set(filtered.keys()) == {"summary", "description", "reporter", "assignee"}


def test_empty_tab_removed_when_no_fields() -> None:
    fields = {
        "summary": _field("summary", required=True),
    }
    tabs = [
        JiraTabDefinition(id="main", label="Details", position=0, fields=["summary"]),
        JiraTabDefinition(id="hf", label="HF Details", position=1, fields=["missing-only"]),
    ]
    _filtered, synced, _required_ids, _order = apply_create_jira_field_policy(fields, tabs)
    assert len(synced) == 1
    assert synced[0].id == "main"


def test_description_override_before_required_ids() -> None:
    fields = {"description": _field("description", required=False)}
    filtered, _tabs, required_ids, _order = apply_create_jira_field_policy(fields, [])
    assert "description" in filtered
    assert "description" in required_ids


def test_reporter_not_required_for_agent() -> None:
    fields = {"reporter": _field("reporter", required=True)}
    filtered, _tabs, required_ids, _order = apply_create_jira_field_policy(fields, [])
    assert "reporter" in filtered
    assert "reporter" not in required_ids


def test_solitary_general_tab_flattened() -> None:
    fields = {
        "summary": _field("summary", required=True),
        "description": _field("description", required=False),
    }
    tabs = [JiraTabDefinition(id="panel-1", label="General", position=0, fields=["summary", "description"])]
    _filtered, synced, _required_ids, _order = apply_create_jira_field_policy(fields, tabs)
    assert synced == []
