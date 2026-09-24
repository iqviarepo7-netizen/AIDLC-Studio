from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from .config import Settings
from .connection_models import JiraConnectionConfig, SessionConnection
from .integrations import direct_jira
from .jira_create_models import (
    CreateJiraAgentRequest,
    CreateJiraAgentResponse,
    CreateJiraIssueRequest,
    CreateJiraIssueResponse,
    CreateJiraMetadataRequest,
    JiraAttachmentConfig,
    JiraCreateMetadata,
    JiraIssueLinkTypeOption,
    JiraIssueSearchOption,
    JiraIssueTypeOption,
    JiraProjectOption,
    PostCreateOperationResult,
    ParsedJiraField,
)
from .jira_create_metadata_policy import apply_create_jira_field_policy
from .jira_issue_link_payload import build_issue_link_payload
from .jira_user_field import is_automatic_or_empty_user_value
from .jira_field_parser import field_order_from_raw, normalize_jira_metadata, schema_is_gh_sprint, status_submittable_on_create
from .jira_create_validation import (
    extract_json_object,
    field_is_empty,
    merge_agent_fields,
    missing_required_fields,
    normalize_create_field_values,
    validate_select_values,
)
from .llm import ModelGateway

logger = logging.getLogger(__name__)


def require_direct_jira(session: SessionConnection) -> JiraConnectionConfig:
    if session.jira.mode != "direct":
        raise HTTPException(
            status_code=503,
            detail="Create Jira requires direct Jira connection (base URL, email, and API token). Reconfigure setup to use direct mode.",
        )
    if not session.jira.base_url or not session.jira.email or not session.jira.api_token:
        raise HTTPException(status_code=400, detail="Jira direct connection is incomplete.")
    return session.jira


async def _secure_request(
    config: JiraConnectionConfig,
    method: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    timeout: float = 45.0,
) -> httpx.Response:
    await direct_jira._ensure_resolved(config)
    scheme = config.auth_scheme or "basic"
    headers: dict[str, str] = {"Accept": "application/json, text/json, */*"}
    extra, auth = direct_jira._auth_for(config, scheme)
    headers.update(extra)
    url = f"{direct_jira._base_url(config)}{path}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if method.upper() == "GET":
            response = await client.get(url, auth=auth, headers=headers, params=data)
        else:
            response = await client.post(url, auth=auth, headers=headers, data=data)
    if response.status_code in {301, 302, 303, 307, 308} or direct_jira._is_html(response):
        raise HTTPException(
            status_code=401,
            detail="Jira returned a login page instead of create-issue metadata. Check VPN/SSO access and API token permissions.",
        )
    return response


async def list_projects(config: JiraConnectionConfig) -> list[JiraProjectOption]:
    response = await direct_jira._request(config, "GET", "/project", timeout=30.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Could not load Jira projects: HTTP {response.status_code}.")
    payload = response.json()
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Unexpected Jira project list response.")
    projects: list[JiraProjectOption] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        project_id = str(item.get("id") or "")
        key = str(item.get("key") or "")
        name = str(item.get("name") or key)
        if project_id and key:
            projects.append(JiraProjectOption(id=project_id, key=key, name=name))
    projects.sort(key=lambda item: item.name.lower())
    return projects


def _issue_type_eligible_for_create_dialog(item: dict[str, Any]) -> bool:
    """Match Jira Create Issue dialog: top-level creatable types only (API-driven, not name filters)."""
    if item.get("subtask") is True:
        return False
    hierarchy = item.get("hierarchyLevel")
    if hierarchy is not None:
        try:
            if int(hierarchy) < 0:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _issue_types_from_createmeta_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    values = data.get("values") or data.get("issueTypes")
    if isinstance(values, list):
        return [item for item in values if isinstance(item, dict)]
    projects = data.get("projects")
    if isinstance(projects, list) and projects:
        project = projects[0]
        if isinstance(project, dict):
            raw = project.get("issuetypes")
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]
    return []


async def list_issue_types(config: JiraConnectionConfig, project_id: str) -> list[JiraIssueTypeOption]:
    version = config.api_version or "2"
    path = f"/issue/createmeta/{project_id}/issuetypes"
    response = await direct_jira._request(config, "GET", path, timeout=30.0)
    if response.status_code == 404 and version == "3":
        response = await direct_jira._request(config, "GET", f"/issue/createmeta?projectIds={project_id}", timeout=30.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Could not load issue types: HTTP {response.status_code}.")
    data = response.json()
    issue_types: list[JiraIssueTypeOption] = []
    for item in _issue_types_from_createmeta_payload(data):
        if not _issue_type_eligible_for_create_dialog(item):
            continue
        type_id = str(item.get("id") or "")
        name = str(item.get("name") or type_id)
        if type_id:
            issue_types.append(JiraIssueTypeOption(id=type_id, name=name, description=item.get("description")))
    return issue_types


async def fetch_quick_create_metadata(config: JiraConnectionConfig, project_id: str, issue_type_id: str) -> dict[str, Any]:
    path = "/secure/QuickCreateIssue!default.jspa"
    response = await _secure_request(
        config,
        "POST",
        path,
        data={
            "decorator": "none",
            "pid": project_id,
            "issuetype": issue_type_id,
        },
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira create metadata failed: HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Jira create metadata response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Jira create metadata response was not an object.")
    return payload


async def fetch_rest_create_fields(config: JiraConnectionConfig, project_id: str, issue_type_id: str) -> dict[str, Any]:
    path = f"/issue/createmeta/{project_id}/issuetypes/{issue_type_id}"
    response = await direct_jira._request(config, "GET", path, timeout=30.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira REST create metadata failed: HTTP {response.status_code}.")
    fields = _fields_from_createmeta_payload(response.json())
    if not fields:
        expanded = await direct_jira._request(
            config,
            "GET",
            f"/issue/createmeta?projectIds={project_id}&issuetypeIds={issue_type_id}&expand=projects.issuetypes.fields",
            timeout=30.0,
        )
        if expanded.status_code < 400:
            fields = _fields_from_createmeta_payload(expanded.json())
    if not fields:
        raise HTTPException(status_code=502, detail="Jira did not return create fields for this project and issue type.")
    return {
        "fields": fields,
        "sortedTabs": [],
    }


def _fields_from_createmeta_payload(data: dict[str, Any]) -> dict[str, Any]:
    values = data.get("values") if isinstance(data.get("values"), list) else []
    fields: dict[str, Any] = {}
    for item in values:
        if isinstance(item, dict):
            field_id = str(item.get("fieldId") or item.get("key") or "")
            if field_id:
                fields[field_id] = _rest_field_definition(field_id, item)
    projects = data.get("projects")
    if isinstance(projects, list):
        for project in projects:
            if not isinstance(project, dict):
                continue
            for issue_type in project.get("issuetypes") or []:
                if not isinstance(issue_type, dict):
                    continue
                raw_fields = issue_type.get("fields")
                if isinstance(raw_fields, dict):
                    for field_id, item in raw_fields.items():
                        if isinstance(item, dict):
                            fields[str(field_id)] = _rest_field_definition(str(field_id), item)
    return fields


def _rest_field_definition(field_id: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": field_id,
        "label": item.get("name") or field_id,
        "required": bool(item.get("required")),
        "editHtml": _rest_field_edit_html(item),
        "schema": item.get("schema") or {},
        "allowedValues": item.get("allowedValues") or [],
        "hasDefaultValue": item.get("hasDefaultValue"),
        "defaultValue": item.get("defaultValue"),
    }


def _rest_field_edit_html(field: dict[str, Any]) -> str:
    schema = field.get("schema") if isinstance(field.get("schema"), dict) else {}
    schema_type = schema.get("type")
    field_id = str(field.get("fieldId") or field.get("key") or "")
    allowed = field.get("allowedValues")
    if isinstance(allowed, list) and allowed:
        options = "".join(
            f'<option value="{html_escape_value(str(item.get("id") or item.get("value") or item.get("name") or ""))}">'
            f"{html_escape_value(str(item.get("name") or item.get("value") or item.get("id") or ""))}</option>"
            for item in allowed
            if isinstance(item, dict)
        )
        return f"<select>{options}</select>"
    if field_id == "description" or schema.get("system") == "description":
        return "<textarea></textarea>"
    if schema_type == "array":
        return "<input type=\"checkbox\" />"
    if schema_type in {"option", "priority", "user", "issuetype", "project"}:
        return "<select></select>"
    if schema.get("custom") and "textarea" in str(schema.get("custom")).lower():
        return "<textarea></textarea>"
    if schema_type in {"date", "datetime"}:
        return "<input type=\"text\" />"
    return "<input type=\"text\" />"


def html_escape_value(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _merge_create_sources(quick_raw: dict[str, Any] | None, rest_raw: dict[str, Any]) -> dict[str, Any]:
    merged_fields: dict[str, Any] = dict(rest_raw.get("fields") or {})
    if quick_raw and isinstance(quick_raw.get("fields"), dict):
        from .jira_field_parser import extract_field_reference

        for raw_key, field_def in quick_raw["fields"].items():
            if not isinstance(field_def, dict):
                continue
            field_id, _ = extract_field_reference(raw_key)
            if not field_id:
                field_id, _ = extract_field_reference(field_def)
            if not field_id:
                continue
            existing = merged_fields.get(field_id, {})
            if not isinstance(existing, dict):
                existing = {}
            merged = {**existing, **field_def, "id": field_id}
            if field_def.get("editHtml"):
                merged["editHtml"] = field_def.get("editHtml")
            incoming_allowed = field_def.get("allowedValues")
            existing_allowed = existing.get("allowedValues")
            if not (isinstance(incoming_allowed, list) and incoming_allowed) and isinstance(
                existing_allowed, list
            ) and existing_allowed:
                merged["allowedValues"] = existing_allowed
            merged_fields[field_id] = merged

    tabs = None
    if quick_raw:
        tabs = quick_raw.get("sortedTabs") or quick_raw.get("sorted_tabs")
    if not tabs:
        tabs = rest_raw.get("sortedTabs")
    return {
        "fields": merged_fields,
        "sortedTabs": tabs or rest_raw.get("sortedTabs") or [],
        "projectKey": (quick_raw or {}).get("projectKey"),
        "issueTypeName": (quick_raw or {}).get("issueTypeName"),
    }


async def get_create_metadata(session: SessionConnection, request: CreateJiraMetadataRequest) -> JiraCreateMetadata:
    config = require_direct_jira(session)
    rest_raw = await fetch_rest_create_fields(config, request.project_id, request.issue_type_id)
    quick_raw: dict[str, Any] | None = None
    try:
        quick_raw = await fetch_quick_create_metadata(config, request.project_id, request.issue_type_id)
    except HTTPException as quick_error:
        if quick_error.status_code not in {401, 403, 502}:
            raise
        logger.info("quick_create_metadata_unavailable project=%s issue_type=%s", request.project_id, request.issue_type_id)
    raw = _merge_create_sources(quick_raw, rest_raw)

    project_key = str(raw.get("projectKey") or "") or None
    parsed_fields, tabs, _fallback_order = normalize_jira_metadata(
        raw,
        project_id=request.project_id,
        issue_type_id=request.issue_type_id,
        project_key=project_key,
        issue_type_name=str(raw.get("issueTypeName") or "") or None,
    )
    parsed_fields, tabs, required_field_ids, policy_order = apply_create_jira_field_policy(parsed_fields, tabs)
    field_order = field_order_from_raw(raw, parsed_fields) or policy_order or _fallback_order
    field_order = [field_id for field_id in field_order if field_id in parsed_fields]
    for field_id in policy_order:
        if field_id not in field_order:
            field_order.append(field_id)
    await _enrich_searchable_user_fields(
        config,
        parsed_fields,
        project_key=project_key,
        project_id=request.project_id,
        issue_type_id=request.issue_type_id,
    )
    await _enrich_sprint_fields(
        config,
        parsed_fields,
        project_key=project_key,
        project_id=request.project_id,
    )
    attachment_config = _attachment_config_from_sources(quick_raw, rest_raw)
    return JiraCreateMetadata(
        project_id=request.project_id,
        issue_type_id=request.issue_type_id,
        project_key=project_key,
        issue_type_name=str(raw.get("issueTypeName") or "") or None,
        fields={key: value for key, value in parsed_fields.items()},
        sorted_tabs=tabs,
        required_field_ids=required_field_ids,
        field_order=field_order,
        attachment_config=attachment_config,
    )


def _assignable_user_search_param_sets(
    config: JiraConnectionConfig,
    *,
    project_key: str | None,
    project_id: str,
    query: str,
    max_results: int,
) -> list[dict[str, str | int]]:
    """Jira Cloud API v3+ uses `query`; legacy Server/DC v2 often uses `username`."""
    base: dict[str, str | int] = {"maxResults": max_results}
    if project_key:
        base["project"] = project_key
    else:
        base["projectId"] = project_id
    needle = query.strip()
    version = config.api_version or "3"
    attempts: list[dict[str, str | int]] = []
    if version == "2":
        params = dict(base)
        if needle:
            params["username"] = needle
        attempts.append(params)
        return attempts

    params = dict(base)
    if needle:
        params["query"] = needle
    attempts.append(params)
    if needle:
        legacy = dict(base)
        legacy["username"] = needle
        attempts.append(legacy)
    return attempts


def _users_from_assignable_search_payload(payload: object) -> list[dict[str, str]]:
    if not isinstance(payload, list):
        return []
    users: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        value = str(item.get("accountId") or item.get("name") or item.get("key") or "")
        label = str(item.get("displayName") or item.get("name") or value)
        if value and label:
            users.append({"label": label, "value": value})
    return users


async def search_assignable_users(
    config: JiraConnectionConfig,
    *,
    project_key: str | None,
    project_id: str,
    query: str = "",
    max_results: int = 20,
) -> list[dict[str, str]]:
    param_sets = _assignable_user_search_param_sets(
        config,
        project_key=project_key,
        project_id=project_id,
        query=query,
        max_results=max_results,
    )
    last_status = 400
    for params in param_sets:
        response = await direct_jira._request(config, "GET", "/user/assignable/search", params=params, timeout=30.0)
        last_status = response.status_code
        if response.status_code < 400:
            return _users_from_assignable_search_payload(response.json())
    raise HTTPException(status_code=502, detail=f"Could not search Jira users: HTTP {last_status}.")


async def _enrich_searchable_user_fields(
    config: JiraConnectionConfig,
    fields: dict[str, ParsedJiraField],
    *,
    project_key: str | None,
    project_id: str,
    issue_type_id: str,
) -> None:
    from .jira_create_models import JiraFieldOption

    for field in fields.values():
        if field.type != "user" or not field.searchable:
            continue
        try:
            users = await search_assignable_users(
                config,
                project_key=project_key,
                project_id=project_id,
                query="",
            )
        except HTTPException:
            continue
        existing = {option.value for option in field.options}
        merged = list(field.options)
        for user in users:
            if user["value"] not in existing:
                merged.append(JiraFieldOption(label=user["label"], value=user["value"]))
                existing.add(user["value"])
        field.options = merged
    _ = issue_type_id


def _parsed_field_is_sprint(field: ParsedJiraField) -> bool:
    raw = field.raw_field if isinstance(field.raw_field, dict) else {}
    schema = raw.get("schema") if isinstance(raw.get("schema"), dict) else {}
    return field.type == "select" and schema_is_gh_sprint(schema)


def _sprint_options_incomplete(field: ParsedJiraField) -> bool:
    if not field.options:
        return True
    return all(not str(option.value).strip() for option in field.options)


async def fetch_project_board_sprints(
    config: JiraConnectionConfig,
    *,
    project_key: str | None,
    project_id: str,
) -> list[dict[str, str]]:
    project_ref = (project_key or "").strip() or project_id
    board_response = await direct_jira._agile_request(
        config,
        "GET",
        "/board",
        params={"projectKeyOrId": project_ref, "maxResults": 50},
    )
    if board_response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Could not load Jira boards: HTTP {board_response.status_code}.")
    board_payload = board_response.json()
    values = board_payload.get("values") if isinstance(board_payload, dict) else None
    if not isinstance(values, list):
        return []
    sprints: list[dict[str, str]] = []
    seen: set[str] = set()
    for board in values:
        if not isinstance(board, dict):
            continue
        board_id = board.get("id")
        if board_id is None:
            continue
        sprint_response = await direct_jira._agile_request(
            config,
            "GET",
            f"/board/{board_id}/sprint",
            params={"state": "active,future", "maxResults": 50},
        )
        if sprint_response.status_code >= 400:
            continue
        sprint_payload = sprint_response.json()
        sprint_values = sprint_payload.get("values") if isinstance(sprint_payload, dict) else None
        if not isinstance(sprint_values, list):
            continue
        for item in sprint_values:
            if not isinstance(item, dict):
                continue
            sprint_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or sprint_id).strip()
            if not sprint_id or sprint_id in seen:
                continue
            seen.add(sprint_id)
            state = str(item.get("state") or "").strip()
            label = f"{state.capitalize()}: {name}" if state and state.lower() not in name.lower() else name
            sprints.append({"label": label, "value": sprint_id})
    return sprints


async def _enrich_sprint_fields(
    config: JiraConnectionConfig,
    fields: dict[str, ParsedJiraField],
    *,
    project_key: str | None,
    project_id: str,
) -> None:
    from .jira_create_models import JiraFieldOption

    needs_enrichment = any(_parsed_field_is_sprint(field) and _sprint_options_incomplete(field) for field in fields.values())
    if not needs_enrichment:
        return
    try:
        remote_sprints = await fetch_project_board_sprints(config, project_key=project_key, project_id=project_id)
    except HTTPException:
        return
    if not remote_sprints:
        return
    for field in fields.values():
        if not _parsed_field_is_sprint(field) or not _sprint_options_incomplete(field):
            continue
        field.options = [JiraFieldOption(label=item["label"], value=item["value"]) for item in remote_sprints]


def _attachment_config_from_sources(
    quick_raw: dict[str, Any] | None,
    rest_raw: dict[str, Any],
) -> JiraAttachmentConfig:
    field_maps: list[dict[str, Any]] = []
    if quick_raw and isinstance(quick_raw.get("fields"), dict):
        field_maps.append(quick_raw["fields"])
    rest_fields = rest_raw.get("fields")
    if isinstance(rest_fields, dict):
        field_maps.append(rest_fields)
    for field_map in field_maps:
        for key, field in field_map.items():
            if not isinstance(field, dict):
                continue
            field_id = str(field.get("id") or field.get("fieldId") or key or "").lower()
            if field_id == "attachment" or "attachment" in field_id:
                return JiraAttachmentConfig(enabled=True)
    if quick_raw:
        return JiraAttachmentConfig(enabled=True)
    return JiraAttachmentConfig(enabled=False)


def _serialize_number_value(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    text = str(value).strip()
    if not text:
        return None
    try:
        num = float(text)
    except ValueError:
        return None
    return int(num) if num.is_integer() else num


def _issue_browse_url(config: JiraConnectionConfig, issue_key: str) -> str | None:
    if not config.base_url:
        return None
    return f"{config.base_url.rstrip('/')}/browse/{issue_key}"


def build_jira_fields_payload(
    metadata: JiraCreateMetadata,
    values: dict[str, Any],
    *,
    api_version: str = "2",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project": {"id": metadata.project_id},
        "issuetype": {"id": metadata.issue_type_id},
    }
    for field_id, field in metadata.fields.items():
        if field_id in {"project", "issuetype", "projectField", "issuetypeField"}:
            continue
        if field.type == "readonly":
            continue
        if field.type == "status" and not status_submittable_on_create(field.raw_field):
            continue
        value = values.get(field_id)
        if field_is_empty(value):
            continue
        if field.type == "number":
            serialized = _serialize_number_value(value)
            if serialized is not None:
                payload[field_id] = serialized
            continue
        if field.type == "checkbox":
            if isinstance(value, list):
                payload[field_id] = [{"id": str(item)} for item in value]
            else:
                payload[field_id] = [{"id": str(value)}]
        elif field.type in {"select", "radio", "status", "priority", "color-picker"}:
            if field_is_empty(value):
                continue
            raw = field.raw_field if isinstance(field.raw_field, dict) else {}
            schema = raw.get("schema") if isinstance(raw.get("schema"), dict) else {}
            if schema_is_gh_sprint(schema):
                sprint_id = str(value).strip()
                if sprint_id.isdigit():
                    payload[field_id] = [int(sprint_id)]
                else:
                    payload[field_id] = [sprint_id]
            else:
                payload[field_id] = {"id": str(value)}
        elif field.type == "user":
            if is_automatic_or_empty_user_value(value):
                continue
            if "@" not in str(value) and not str(value).isdigit() and len(str(value)) > 20:
                payload[field_id] = {"accountId": str(value)}
            elif str(value).isdigit():
                payload[field_id] = {"id": str(value)}
            else:
                payload[field_id] = {"name": str(value)}
        elif field.type == "parent":
            if field_is_empty(value):
                continue
            if str(value).isdigit():
                payload[field_id] = {"id": str(value)}
            else:
                payload[field_id] = {"key": str(value)}
        elif field.type == "labels":
            if isinstance(value, list):
                payload[field_id] = [str(item).strip() for item in value if str(item).strip()]
            elif isinstance(value, str) and value.strip():
                payload[field_id] = [part.strip() for part in value.split(",") if part.strip()]
        elif field.type in {"date", "datetime"}:
            payload[field_id] = str(value)
        elif field_id == "description" and api_version == "3":
            payload[field_id] = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": str(value)}]}],
            }
        else:
            payload[field_id] = str(value)
    return payload


async def search_issues(
    config: JiraConnectionConfig,
    *,
    project_id: str,
    query: str = "",
    max_results: int = 20,
) -> list[JiraIssueSearchOption]:
    params: dict[str, str | int] = {
        "query": query.strip(),
        "currentProjectId": project_id,
        "showSubTasks": "true",
        "maxResults": max_results,
    }
    response = await direct_jira._request(config, "GET", "/issue/picker", params=params, timeout=30.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Could not search Jira issues: HTTP {response.status_code}.")
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    issues: list[JiraIssueSearchOption] = []
    seen: set[str] = set()
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("issues") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            summary = str(item.get("summaryText") or item.get("summary") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            label = f"{key} — {summary}".strip(" —") if summary else key
            issues.append(JiraIssueSearchOption(label=label, value=key))
    return issues


async def list_issue_link_types(config: JiraConnectionConfig) -> list[JiraIssueLinkTypeOption]:
    response = await direct_jira._request(config, "GET", "/issueLinkType", timeout=30.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Could not load Jira issue link types: HTTP {response.status_code}.")
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    raw_types = payload.get("issueLinkTypes")
    if not isinstance(raw_types, list):
        return []
    options: list[JiraIssueLinkTypeOption] = []
    for item in raw_types:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("id") or "")
        name = str(item.get("name") or type_id)
        inward = str(item.get("inward") or "")
        outward = str(item.get("outward") or "")
        if type_id:
            options.append(JiraIssueLinkTypeOption(id=type_id, name=name, inward=inward, outward=outward))
    return options


async def create_issue_link(
    config: JiraConnectionConfig,
    *,
    new_issue_key: str,
    target_issue_key: str,
    link_type_id: str,
    new_issue_role: str = "outward",
) -> None:
    role = "inward" if new_issue_role == "inward" else "outward"
    body = build_issue_link_payload(
        new_issue_key=new_issue_key,
        target_issue_key=target_issue_key,
        link_type_id=link_type_id,
        new_issue_role=role,
    )
    response = await direct_jira._request(config, "POST", "/issueLink", json=body, timeout=30.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=422, detail=_parse_jira_error(response))


async def create_issue(session: SessionConnection, request: CreateJiraIssueRequest) -> CreateJiraIssueResponse:
    config = require_direct_jira(session)
    metadata = await get_create_metadata(
        session,
        CreateJiraMetadataRequest(project_id=request.project_id, issue_type_id=request.issue_type_id),
    )
    merged = normalize_create_field_values(dict(request.fields))
    missing = missing_required_fields(metadata, merged)
    if missing:
        labels = ", ".join(item.label for item in missing)
        raise HTTPException(status_code=422, detail=f"Required Jira fields are missing: {labels}.")
    option_errors = validate_select_values(metadata, merged)
    if option_errors:
        raise HTTPException(status_code=422, detail="; ".join(option_errors.values()))

    fields_payload = build_jira_fields_payload(metadata, merged, api_version=config.api_version or "2")
    response = await direct_jira._request(config, "POST", "/issue", json={"fields": fields_payload}, timeout=45.0)
    if response.status_code >= 400:
        detail = _parse_jira_error(response)
        raise HTTPException(status_code=422, detail=detail)
    data = response.json()
    key = str(data.get("key") or "")
    if not key:
        raise HTTPException(status_code=502, detail="Jira did not return an issue key.")
    key = key.upper()
    post_ops: list[PostCreateOperationResult] = []
    partial = False
    for link in request.issue_links or []:
        try:
            await create_issue_link(
                config,
                new_issue_key=key,
                target_issue_key=link.target_issue_key,
                link_type_id=link.link_type_id,
                new_issue_role=link.new_issue_role,
            )
            post_ops.append(
                PostCreateOperationResult(
                    operation=f"link:{link.target_issue_key.upper()}",
                    success=True,
                )
            )
        except HTTPException as link_error:
            partial = True
            post_ops.append(
                PostCreateOperationResult(
                    operation=f"link:{link.target_issue_key.upper()}",
                    success=False,
                    detail=str(link_error.detail),
                )
            )
    message = None
    if partial:
        message = f"Jira {key} was created successfully, but some additional operations could not be completed."
    return CreateJiraIssueResponse(
        key=key,
        id=str(data.get("id") or "") or None,
        self_url=data.get("self"),
        browse_url=_issue_browse_url(config, key),
        partial_success=partial,
        message=message,
        post_create_operations=post_ops,
    )


MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS_PER_REQUEST = 20


def _safe_attachment_filename(name: str) -> str:
    cleaned = (name or "attachment").replace("\\", "/").split("/")[-1].strip()
    return cleaned[:255] if cleaned else "attachment"


async def upload_issue_attachments(
    config: JiraConnectionConfig,
    issue_key: str,
    files: list[tuple[str, bytes, str | None]],
) -> list[PostCreateOperationResult]:
    if not files:
        return []
    if len(files) > MAX_ATTACHMENTS_PER_REQUEST:
        raise HTTPException(status_code=422, detail=f"At most {MAX_ATTACHMENTS_PER_REQUEST} attachments are allowed per request.")
    await direct_jira._ensure_resolved(config)
    scheme = config.auth_scheme or "basic"
    headers = {"Accept": "application/json", "X-Atlassian-Token": "no-check"}
    extra, auth = direct_jira._auth_for(config, scheme)
    headers.update(extra)
    url = f"{direct_jira._base_url(config)}/issue/{issue_key}/attachments"
    results: list[PostCreateOperationResult] = []
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
        for filename, content, content_type in files:
            safe_name = _safe_attachment_filename(filename)
            if len(content) > MAX_ATTACHMENT_BYTES:
                results.append(
                    PostCreateOperationResult(
                        operation=f"attachment:{safe_name}",
                        success=False,
                        detail="Attachment exceeds the maximum allowed size.",
                    )
                )
                continue
            multipart = [("file", (safe_name, content, content_type or "application/octet-stream"))]
            response = await client.post(url, auth=auth, headers=headers, files=multipart)
            if response.status_code >= 400:
                results.append(
                    PostCreateOperationResult(
                        operation=f"attachment:{safe_name}",
                        success=False,
                        detail=_parse_jira_error(response),
                    )
                )
            else:
                results.append(PostCreateOperationResult(operation=f"attachment:{safe_name}", success=True))
    return results


def _parse_jira_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if isinstance(errors, dict) and errors:
                return "; ".join(f"{key}: {value}" for key, value in errors.items())
            error_messages = payload.get("errorMessages")
            if isinstance(error_messages, list) and error_messages:
                return "; ".join(str(item) for item in error_messages)
    except ValueError:
        pass
    return f"Jira create issue failed: HTTP {response.status_code}."


async def run_create_jira_agent(
    session: SessionConnection,
    settings: Settings,
    request: CreateJiraAgentRequest,
) -> CreateJiraAgentResponse:
    from .jira_create_agent import analyze_requirement

    metadata = await get_create_metadata(
        session,
        CreateJiraMetadataRequest(project_id=request.project_id, issue_type_id=request.issue_type_id),
    )
    config = require_direct_jira(session)
    gateway = ModelGateway(settings)
    provider_name = "groq" if settings.groq_api_key else "gemini"
    provider = gateway.provider(provider_name)
    return await analyze_requirement(provider, metadata, request, config)
