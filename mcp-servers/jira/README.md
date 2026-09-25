# AIDLC Studio — Jira MCP (HTTP)

HTTP MCP server that AIDLC Studio talks to when **Jira mode = MCP**.

Studio's Connect form:

- **MCP URL** → `http://localhost:9001` (the MCP process, not Jira)
- **Base URL** → Jira site, e.g. `https://your-site.atlassian.net`
- **Email** → Atlassian account email
- **Jira API token** → Atlassian API token (sent as `Authorization: Bearer`)

`.env` values are only a fallback if a form field is empty.

## Tools

| Tool | Purpose |
|---|---|
| `health` | Used by Validate & Connect |
| `get_issue` | Fetch a Jira issue |
| `transition_issue` | Move issue by transition ID |
| `add_comment` | Add a comment (PR publish) |

These names match `backend/config/policy.yaml` (`mcp.jira.tools`).

## Run

```powershell
cd mcp-servers/jira
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn main:app --reload --port 9001
```

## Connect in AIDLC Studio

1. Start this MCP on port 9001.
2. Start Studio backend + frontend as usual.
3. On **Connect Jira & Git**:
   - Jira → **MCP**
   - MCP URL → `http://localhost:9001`
   - Base URL → your Jira site
   - Email → Atlassian account email
   - Jira API token → Atlassian token (no quotes)
   - Git → **Direct** with your local repo path
4. Click **Validate & Connect**.

## Quick check

```powershell
curl http://localhost:9001/
curl -X POST http://localhost:9001/tools/call -H "Content-Type: application/json" -H "Authorization: Bearer YOUR_JIRA_API_TOKEN" -H "X-Jira-Base-Url: https://your-site.atlassian.net" -H "X-Jira-Email: you@company.com" -d "{\"name\":\"health\",\"arguments\":{}}"
```
