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
    JiraCreateMetadata,
    JiraIssueTypeOption,
    JiraProjectOption,
)
from .jira_create_metadata_policy import apply_create_jira_field_policy
from .jira_field_parser import normalize_jira_metadata
from .jira_create_validation import (
    extract_json_object,
    field_is_empty,
    merge_agent_fields,
    missing_required_fields,
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


async def list_issue_types(config: JiraConnectionConfig, project_id: str) -> list[JiraIssueTypeOption]:
    version = config.api_version or "2"
    path = f"/issue/createmeta/{project_id}/issuetypes"
    response = await direct_jira._request(config, "GET", path, timeout=30.0)
    if response.status_code == 404 and version == "3":
        response = await direct_jira._request(config, "GET", f"/issue/createmeta?projectIds={project_id}", timeout=30.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Could not load issue types: HTTP {response.status_code}.")
    data = response.json()
    values = data.get("values") or data.get("issueTypes") or data.get("projects", [{}])[0].get("issuetypes", [])
    issue_types: list[JiraIssueTypeOption] = []
    if isinstance(values, list):
        for item in values:
            if not isinstance(item, dict):
                continue
            type_id = str(item.get("id") or "")
            name = str(item.get("name") or type_id)
            if type_id:
                issue_types.append(JiraIssueTypeOption(id=type_id, name=name, description=item.get("description")))
    issue_types.sort(key=lambda item: item.name.lower())
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

    parsed_fields, tabs = normalize_jira_metadata(
        raw,
        project_id=request.project_id,
        issue_type_id=request.issue_type_id,
        project_key=str(raw.get("projectKey") or "") or None,
        issue_type_name=str(raw.get("issueTypeName") or "") or None,
    )
    parsed_fields, tabs = apply_create_jira_field_policy(parsed_fields, tabs)
    return JiraCreateMetadata(
        project_id=request.project_id,
        issue_type_id=request.issue_type_id,
        project_key=str(raw.get("projectKey") or "") or None,
        issue_type_name=str(raw.get("issueTypeName") or "") or None,
        fields={key: value for key, value in parsed_fields.items()},
        sorted_tabs=tabs,
    )


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
        value = values.get(field_id)
        if field_is_empty(value):
            continue
        if field.type == "checkbox":
            if isinstance(value, list):
                payload[field_id] = [{"id": str(item)} for item in value]
            else:
                payload[field_id] = [{"id": str(value)}]
        elif field.type in {"select", "radio"}:
            payload[field_id] = {"id": str(value)}
        elif field_id == "description" and api_version == "3":
            payload[field_id] = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": str(value)}]}],
            }
        else:
            payload[field_id] = str(value)
    return payload


async def create_issue(session: SessionConnection, request: CreateJiraIssueRequest) -> CreateJiraIssueResponse:
    config = require_direct_jira(session)
    metadata = await get_create_metadata(
        session,
        CreateJiraMetadataRequest(project_id=request.project_id, issue_type_id=request.issue_type_id),
    )
    merged = dict(request.fields)
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
    return CreateJiraIssueResponse(key=key.upper(), id=str(data.get("id") or "") or None, self_url=data.get("self"))


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
    gateway = ModelGateway(settings)
    provider_name = "groq" if settings.groq_api_key else "gemini"
    provider = gateway.provider(provider_name)
    return await analyze_requirement(provider, metadata, request)
