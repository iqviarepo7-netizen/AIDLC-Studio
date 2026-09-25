from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connection_models import JiraConnectionConfig
from app.jira_create_service import upload_issue_attachments


@pytest.mark.asyncio
async def test_attachment_partial_success_returns_per_file_results() -> None:
    config = JiraConnectionConfig(
        mode="direct",
        base_url="https://jira.example.com",
        email="u@example.com",
        api_token="token",
        api_version="2",
        auth_scheme="basic",
    )

    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.text = ""

        def json(self):
            return {}

    client = MagicMock()

    async def post(*_args, **_kwargs):
        if client.post.call_count == 1:
            return FakeResponse(201)
        return FakeResponse(400)

    client.post = AsyncMock(side_effect=post)

    with patch("app.jira_create_service.direct_jira._ensure_resolved", AsyncMock()):
        with patch("app.jira_create_service.direct_jira._auth_for", return_value=({}, ("u", "t"))):
            with patch("app.jira_create_service.direct_jira._base_url", return_value="https://jira.example.com/rest/api/2"):
                with patch("httpx.AsyncClient") as client_cls:
                    client_cls.return_value.__aenter__.return_value = client
                    results = await upload_issue_attachments(
                        config,
                        "SCR-1",
                        [("a.txt", b"a", "text/plain"), ("b.txt", b"b", "text/plain")],
                    )
    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is False
