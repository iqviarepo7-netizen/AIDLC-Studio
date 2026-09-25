# AIDLC Studio

Fully configurable, MCP-first, agentic Jira-to-PR automation platform with an IDE-style React workspace.

## What it does

1. Accept a Jira issue key
2. Fetch the issue through external **Jira MCP**
3. Run sub-agents for requirement analysis, complexity scoring, model routing, planning, and implementation
4. Execute configured terminal validation commands
5. Auto-retry with the next configured model tier on validation failure
6. Publish through **Git MCP** (push + PR) and **Jira MCP** (transition + comment)
7. Stream agent and MCP activity in the AIDLC Studio UI

## Run locally

1. Copy [`backend/.env.example`](backend/.env.example) to `backend/.env`
2. Configure MCP server URLs/tokens, repository path, and Gemini API key
3. Review policy files in [`backend/config/`](backend/config/) — runtime behavior is config-driven, not hardcoded
4. *(Optional MCP)* Start the bundled Jira MCP:

```powershell
cd mcp-servers/jira
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn main:app --reload --port 9001
```

In the Connect screen: Jira → **MCP**, MCP URL → `http://localhost:9001`, then Base URL, email, and Jira API token.  
See [`mcp-servers/jira/README.md`](mcp-servers/jira/README.md). For a quick demo without MCP, use Jira **Direct** instead.

5. Start the API:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

6. Start the UI:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Configuration

| File | Purpose |
|---|---|
| [`backend/config/policy.yaml`](backend/config/policy.yaml) | Automation mode, model routing, MCP tool map, validation commands, guardrails |
| [`backend/config/agents.yaml`](backend/config/agents.yaml) | Agent behavior and prompt template paths |
| [`backend/config/ui.yaml`](backend/config/ui.yaml) | Studio branding, theme tokens, stage labels |
| [`backend/.env`](backend/.env) | Secrets and environment substitution values |

Set `automation.mode: review_required` in `policy.yaml` if you want the workflow to pause before MCP publish.

## API

- `POST /api/workflows` — create and auto-run pipeline
- `GET /api/workflows/{id}` — workflow state for the studio UI
- `GET /api/workflows/{id}/files/{path}` — generated file content
- `GET /api/config/public` — UI theme and stage labels
- `GET /api/llm/providers/{provider}/models` — discover models (Groq)
- `GET /api/llm/configuration` — routing, key chain ids, configured models
- `GET /health` — MCP/model/repository readiness

## Tests

```powershell
cd backend
pytest tests/ -q
```
