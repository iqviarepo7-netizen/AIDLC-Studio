from __future__ import annotations

from typing import Any, Literal

NewIssueLinkRole = Literal["outward", "inward"]


def build_issue_link_payload(
    *,
    new_issue_key: str,
    target_issue_key: str,
    link_type_id: str,
    new_issue_role: NewIssueLinkRole,
) -> dict[str, Any]:
    """
    Map UI semantics to Jira /issueLink payload.

    Jira describes outwardIssue using the link type's *outward* verb and inwardIssue using *inward*.
    When the new issue plays the outward role: new blocks target (outward verb on new).
    When the new issue plays the inward role: new is blocked by target (inward verb on new).
    """
    new_key = new_issue_key.strip().upper()
    target_key = target_issue_key.strip().upper()
    body: dict[str, Any] = {"type": {"id": link_type_id}}
    if new_issue_role == "outward":
        body["outwardIssue"] = {"key": new_key}
        body["inwardIssue"] = {"key": target_key}
    else:
        body["outwardIssue"] = {"key": target_key}
        body["inwardIssue"] = {"key": new_key}
    return body
