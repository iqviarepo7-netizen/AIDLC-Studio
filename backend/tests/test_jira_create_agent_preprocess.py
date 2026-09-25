from app.jira_create_models import JiraCreateMetadata, ParsedJiraField, JiraFieldOption
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


def test_preprocess_splits_full_create_jira_prompt() -> None:
    metadata = JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user"),
            "customfield_start": ParsedJiraField(id="customfield_start", label="Start date", required=False, type="date"),
            "priority": ParsedJiraField(
                id="priority",
                label="Priority",
                required=False,
                type="priority",
                options=[JiraFieldOption(label="High", value="2")],
            ),
            "labels": ParsedJiraField(id="labels", label="Labels", required=False, type="labels"),
            "customfield_sprint": ParsedJiraField(
                id="customfield_sprint",
                label="Sprint",
                required=False,
                type="select",
                raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            ),
        },
        sorted_tabs=[],
    )
    text = (
        "add a popup after user clicks run pipeline. popup should say welcome home. "
        "assign it to mohan. start date should be 5 days from today. priority is high. "
        "add labels test and develop. mark it as active sprint."
    )
    result = preprocess_user_message(text, metadata)
    lowered = result.requirement.lower()
    assert "mohan" not in lowered
    assert "priority" not in lowered
    assert "label" not in lowered
    assert "sprint" not in lowered
    assert "5 days" not in lowered
    assert result.provided_fields["assignee"].lower().startswith("mohan")
    assert "5 days from today" in result.provided_fields["customfield_start"]
    assert result.provided_fields["priority"].lower() == "high"
    assert result.provided_fields["labels"] == "test and develop"
    assert result.provided_fields["customfield_sprint"] == "active sprint"


def _full_prompt_metadata() -> JiraCreateMetadata:
    return JiraCreateMetadata(
        project_id="1",
        issue_type_id="2",
        fields={
            "summary": ParsedJiraField(id="summary", label="Summary", required=True, type="text"),
            "description": ParsedJiraField(id="description", label="Description", required=True, type="textarea"),
            "assignee": ParsedJiraField(id="assignee", label="Assignee", required=False, type="user"),
            "duedate": ParsedJiraField(id="duedate", label="Due date", required=False, type="date"),
            "customfield_start": ParsedJiraField(id="customfield_start", label="Start date", required=False, type="date"),
            "priority": ParsedJiraField(id="priority", label="Priority", required=False, type="priority"),
            "labels": ParsedJiraField(id="labels", label="Labels", required=False, type="labels"),
            "parent": ParsedJiraField(id="parent", label="Parent", required=False, type="parent", searchable=True),
            "customfield_sprint": ParsedJiraField(
                id="customfield_sprint",
                label="Sprint",
                required=False,
                type="select",
                raw_field={"schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            ),
            "customfield_story": ParsedJiraField(
                id="customfield_story",
                label="Story Points",
                required=False,
                type="number",
            ),
        },
        sorted_tabs=[],
    )


EXACT_TEST_PROMPT = (
    "add a popup after when user clicks run pipeline. popup should say welcome home. "
    "assign it to iqvia. start date should be 6 days from today. priority is high. "
    "add labels test and develop. mark it as future sprint. due date as next week friday. "
    "parent jira is scrum 5. story point is 5. "
    "linked work items is that this jira issue clone scrum 8"
)


def test_preprocess_exact_prompt_separates_requirement_from_jira_fields() -> None:
    result = preprocess_user_message(EXACT_TEST_PROMPT, _full_prompt_metadata())
    lowered = result.requirement.lower()
    assert "welcome home" in lowered
    assert "run pipeline" in lowered
    for leak in (
        "iqvia",
        "priority",
        "label",
        "sprint",
        "due date",
        "start date",
        "parent",
        "story point",
        "linked work",
        "clone",
        "scrum 5",
        "scrum 8",
    ):
        assert leak not in lowered, leak
    assert result.provided_fields["assignee"].lower() == "iqvia"
    assert "6 days from today" in result.provided_fields["customfield_start"]
    assert result.provided_fields["priority"].lower() == "high"
    assert result.provided_fields["labels"] == "test and develop"
    assert result.provided_fields["customfield_sprint"] == "future sprint"
    assert "next week friday" in result.provided_fields["duedate"].lower()
    assert result.provided_fields["parent"].lower() in {"scrum 5", "scrum-5"}
    assert result.provided_fields["customfield_story"] == "5"
    assert len(result.linked_work_items) == 1
    assert result.linked_work_items[0].relationship_intent.lower() == "clone"
    assert result.linked_work_items[0].target_intent.lower() in {"scrum 8", "scrum-8"}
