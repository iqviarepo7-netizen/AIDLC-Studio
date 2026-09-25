from __future__ import annotations

import logging
from typing import Any, Literal

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

from ..connection_models import JiraConnectionConfig
from ..models import JiraTask

AuthScheme = Literal["basic", "bearer"]
ApiVersion = Literal["2", "3"]


def _token(config: JiraConnectionConfig) -> str:
    token = (config.api_token or "").strip().rstrip("|").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Jira email and API token are required for direct mode.")
    return token


def _email(config: JiraConnectionConfig) -> str:
    email = (config.email or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Jira email and API token are required for direct mode.")
    return email


def _base_url(config: JiraConnectionConfig) -> str:
    if not config.base_url:
        raise HTTPException(status_code=400, detail="Jira base URL is required for direct mode.")
    return config.base_url.rstrip("/")


def _auth_for(config: JiraConnectionConfig, scheme: AuthScheme) -> tuple[dict[str, str], tuple[str, str] | None]:
    token = _token(config)
    if scheme == "basic":
        return {}, (_email(config), token)
    return {"Authorization": f"Bearer {token}"}, None


def _is_html(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" in content_type:
        return True
    text = response.text[:80].lstrip().lower()
    return text.startswith("<!doctype") or text.startswith("<html")


async def _request(
    config: JiraConnectionConfig,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, str | int] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    await _ensure_resolved(config)
    version = config.api_version or "3"
    scheme: AuthScheme = config.auth_scheme or "basic"
    headers = {"Accept": "application/json"}
    extra, auth = _auth_for(config, scheme)
    headers.update(extra)
    url = f"{_base_url(config)}/rest/api/{version}{path}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.request(method, url, auth=auth, headers=headers, json=json, params=params)
    if response.status_code in {301, 302, 303, 307, 308} or _is_html(response):
        raise HTTPException(
            status_code=401,
            detail="Jira returned a login page instead of the REST API. Check VPN/SSO access and that the token is a REST API token or personal access token.",
        )
    return response


async def _agile_request(
    config: JiraConnectionConfig,
    method: str,
    path: str,
    *,
    params: dict[str, str | int] | None = None,
    json: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    await _ensure_resolved(config)
    scheme: AuthScheme = config.auth_scheme or "basic"
    headers = {"Accept": "application/json"}
    if json is not None:
        headers["Content-Type"] = "application/json"
    extra, auth = _auth_for(config, scheme)
    headers.update(extra)
    url = f"{_base_url(config)}/rest/agile/1.0{path}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.request(method, url, auth=auth, headers=headers, params=params, json=json)
    if response.status_code in {301, 302, 303, 307, 308} or _is_html(response):
        raise HTTPException(
            status_code=401,
            detail="Jira returned a login page instead of the REST API. Check VPN/SSO access and that the token is a REST API token or personal access token.",
        )
    return response


async def _ensure_resolved(config: JiraConnectionConfig) -> None:
    if config.api_version and config.auth_scheme:
        return
    versions: list[ApiVersion] = [config.api_version] if config.api_version else ["3", "2"]
    schemes: list[AuthScheme] = [config.auth_scheme] if config.auth_scheme else ["basic", "bearer"]
    last_status: int | None = None
    saw_html = False
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        for version in versions:
            for scheme in schemes:
                headers = {"Accept": "application/json"}
                extra, auth = _auth_for(config, scheme)
                headers.update(extra)
                url = f"{_base_url(config)}/rest/api/{version}/myself"
                response = await client.get(url, auth=auth, headers=headers)
                last_status = response.status_code
                if response.status_code in {301, 302, 303, 307, 308} or _is_html(response):
                    saw_html = True
                    continue
                if response.status_code in {401, 403}:
                    continue
                if response.status_code == 404:
                    continue
                if response.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"Jira connection failed: HTTP {response.status_code}.")
                config.api_version = version
                config.auth_scheme = scheme
                logger.info("jira_auth_resolved api_version=%s auth_scheme=%s", version, scheme)
                return
    if saw_html:
        raise HTTPException(
            status_code=401,
            detail="Jira returned a login page instead of the REST API. Check VPN/SSO access and that the token is a REST API token or personal access token.",
        )
    if last_status in {401, 403}:
        raise HTTPException(status_code=401, detail="Jira authentication failed. Check email and API token.")
    raise HTTPException(status_code=502, detail=f"Jira connection failed: HTTP {last_status or 'unknown'}.")


async def validate_connection(config: JiraConnectionConfig) -> str:
    await _ensure_resolved(config)
    response = await _request(config, "GET", "/myself", timeout=20.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira connection failed: HTTP {response.status_code}.")
    data = response.json()
    display = data.get("displayName") or data.get("emailAddress") or "authenticated user"
    return f"Connected as {display}"


def parse_issue(data: dict[str, Any], jira_key: str, *, base_url: str | None = None) -> JiraTask:
    fields = data.get("fields", data) if isinstance(data.get("fields", data), dict) else {}
    description = fields.get("description")
    if isinstance(description, dict):
        description = " ".join(_walk_adf(description))
    key = str(data.get("key") or jira_key).upper()
    status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    status_category = status.get("statusCategory") if isinstance(status.get("statusCategory"), dict) else {}
    labels = fields.get("labels") or data.get("labels") or []
    return JiraTask(
        key=key,
        summary=str(fields.get("summary") or data.get("summary") or key),
        description=str(description) if description else None,
        issue_type=(fields.get("issuetype") or {}).get("name", data.get("issue_type", "TASK")),
        priority=(fields.get("priority") or {}).get("name", data.get("priority")),
        status=_named(status) or _string(data.get("status")),
        status_category=_named(status_category) or _string(status_category.get("key")),
        assignee=_person_name(fields.get("assignee") or data.get("assignee")),
        assignee_email=_person_email(fields.get("assignee") or data.get("assignee")),
        reporter=_person_name(fields.get("reporter") or data.get("reporter")),
        labels=[str(label) for label in labels] if isinstance(labels, list) else [],
        url=_browse_url(data, key, base_url),
        acceptance_criteria=list(data.get("acceptance_criteria") or fields.get("acceptance_criteria") or []),
    )


async def fetch_issue(config: JiraConnectionConfig, jira_key: str) -> JiraTask:
    response = await _request(config, "GET", f"/issue/{jira_key.upper()}")
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Jira issue {jira_key} was not found.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira fetch failed: HTTP {response.status_code}.")
    return parse_issue(response.json(), jira_key, base_url=_base_url(config))


def _comment_payload(config: JiraConnectionConfig, comment: str) -> dict[str, Any]:
    if config.api_version == "2":
        return {"body": comment}
    return {"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}]}}


async def comment_issue(config: JiraConnectionConfig, jira_key: str, comment: str) -> None:
    response = await _request(config, "POST", f"/issue/{jira_key.upper()}/comment", json=_comment_payload(config, comment), timeout=20.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira comment failed: HTTP {response.status_code}.")


async def list_comment_texts(config: JiraConnectionConfig, jira_key: str) -> list[str]:
    response = await _request(config, "GET", f"/issue/{jira_key.upper()}/comment", timeout=20.0)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira comment fetch failed: HTTP {response.status_code}.")
    comments = response.json().get("comments", [])
    texts: list[str] = []
    for comment in comments:
        body = comment.get("body")
        if isinstance(body, dict):
            texts.append(" ".join(_walk_adf(body)))
        elif isinstance(body, str):
            texts.append(body)
    logger.info("jira_comments_loaded jira_key=%s count=%s", jira_key.upper(), len(texts))
    return texts


async def has_pr_comment(config: JiraConnectionConfig, jira_key: str, pr_url: str) -> bool:
    if not pr_url:
        return False
    needle = pr_url.strip().lower()
    for text in await list_comment_texts(config, jira_key):
        if needle in text.lower():
            logger.info("jira_pr_comment_found jira_key=%s pr_url=%s", jira_key.upper(), pr_url)
            return True
    logger.info("jira_pr_comment_missing jira_key=%s pr_url=%s", jira_key.upper(), pr_url)
    return False


async def transition_issue(config: JiraConnectionConfig, jira_key: str, transition_id: str) -> None:
    response = await _request(
        config,
        "POST",
        f"/issue/{jira_key.upper()}/transitions",
        json={"transition": {"id": transition_id}},
        timeout=20.0,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Jira transition failed: HTTP {response.status_code}.")


def _named(value: object) -> str | None:
    if isinstance(value, dict) and value.get("name"):
        return str(value["name"])
    return None


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _person_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return _string(value)
    return _string(value.get("displayName")) or _string(value.get("name")) or _string(value.get("emailAddress"))


def _person_email(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    return _string(value.get("emailAddress"))


def _browse_url(data: dict[str, Any], key: str, base_url: str | None) -> str | None:
    if base_url:
        return f"{base_url.rstrip('/')}/browse/{key}"
    self_url = data.get("self")
    if isinstance(self_url, str) and "/rest/" in self_url:
        return f"{self_url.split('/rest/', 1)[0]}/browse/{key}"
    return None


def _walk_adf(value: object) -> list[str]:
    if isinstance(value, dict):
        parts = [part for child in value.get("content", []) for part in _walk_adf(child)]
        if isinstance(value.get("text"), str):
            parts.append(value["text"])
        return parts
    if isinstance(value, list):
        return [part for child in value for part in _walk_adf(child)]
    return []
