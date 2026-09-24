# AIDLC Studio — Jira MCP (HTTP)

HTTP MCP server that AIDLC Studio talks to when **Jira mode = MCP**.

Studio's Connect form field **MCP URL** should be:

```text
http://localhost:9001
```

Jira email/token go in **this** server's `.env`, not in the Studio form.

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
# Edit .env with JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
uvicorn main:app --reload --port 9001
```

## Connect in AIDLC Studio

1. Start this MCP on port 9001.
2. Start Studio backend + frontend as usual.
3. On **Connect Jira & Git**:
   - Jira → **MCP**
   - MCP URL → `http://localhost:9001`
   - MCP token → only if you set `MCP_AUTH_TOKEN`
   - Done transition ID → optional
   - Git → **Direct** (simplest) with your local repo path
4. Click **Validate & Connect**.

## Quick check

```powershell
curl http://localhost:9001/
curl -X POST http://localhost:9001/tools/call -H "Content-Type: application/json" -d "{\"name\":\"health\",\"arguments\":{}}"
```
