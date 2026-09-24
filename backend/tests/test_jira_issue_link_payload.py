from app.jira_issue_link_payload import build_issue_link_payload


def test_new_issue_outward_role_blocks_target() -> None:
    payload = build_issue_link_payload(
        new_issue_key="new-1",
        target_issue_key="scr-2",
        link_type_id="100",
        new_issue_role="outward",
    )
    assert payload == {
        "type": {"id": "100"},
        "outwardIssue": {"key": "NEW-1"},
        "inwardIssue": {"key": "SCR-2"},
    }


def test_new_issue_inward_role_is_blocked_by_target() -> None:
    payload = build_issue_link_payload(
        new_issue_key="new-1",
        target_issue_key="scr-2",
        link_type_id="100",
        new_issue_role="inward",
    )
    assert payload == {
        "type": {"id": "100"},
        "outwardIssue": {"key": "SCR-2"},
        "inwardIssue": {"key": "NEW-1"},
    }
