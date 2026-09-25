# AIDLC Studio — Implementation Guide

This document describes the architecture, core principles, MCP integration, agent model, guardrails, and configuration rules for the Jira-to-PR automation platform.

---

## Core Principles

| Principle | Meaning |
|---|---|
| **MCP-first** | All Jira and Git operations go through the `MCPAdapter`. Agents never call Jira or Git APIs directly. |
| **Agentic orchestration** | A main `Orchestrator` delegates work to specialized sub-agents. Each agent has a single responsibility. |
| **Zero human intervention (default)** | With `automation.mode: full`, one Jira key triggers the full pipeline through PR creation and Jira update. |
| **Configuration over code** | Models, complexity rules, MCP tool names, validation commands, retry policy, and guardrails live in YAML + `.env` — not in Python business logic. |
| **Guarded by default** | Every MCP request and response passes through guardrails before it affects the workflow. |
| **Auditable** | Workflow events and MCP calls are recorded with redacted payloads for traceability. |

---

## Ideology

AIDLC Studio treats software delivery as a **controlled pipeline**, not open-ended autonomy:

1. **Read** the requirement from Jira (via MCP).
2. **Understand** scope and complexity (deterministic agents).
3. **Choose** the smallest sufficient model (token-efficient routing).
4. **Plan and implement** against an existing repository (LLM + Git MCP).
5. **Prove** correctness with configured terminal validation.
6. **Publish** only after validation passes (Git MCP push/PR, Jira MCP status/comment).

External integrations are **replaceable boundaries**. The orchestrator and agents stay stable; only MCP servers and config change when integrations change.

Human review is optional (`review_required` mode), not the default. Retries on validation failure escalate to a stronger model tier rather than requiring manual intervention.

---

## Architecture

```
User (AIDLC Studio UI)
        │
        ▼
FastAPI Orchestrator ──────────────────────────────┐
        │                                           │
        ├── TaskAnalyzerAgent                       │
        ├── ComplexityAgent                         │
        ├── ModelSelectorAgent                      │
        ├── PlanningAgent                           │
        ├── ImplementationAgent ──► ModelGateway    │
        ├── ValidatorAgent ──► TerminalRunner       │
        ├── PublisherAgent                          │
        └── ReportAgent                             │
                │                                   │
                ▼                                   │
         MCPAdapter + Guardrails ◄──────────────────┘
                │
        ┌───────┴───────┐
        ▼               ▼
   Jira MCP         Git MCP
   (external)       (external)
```

### Key modules

| Module | Path | Role |
|---|---|---|
| Orchestrator | `backend/app/workflow.py` | Runs the end-to-end pipeline and state machine |
| MCP Adapter | `backend/app/mcp/adapter.py` | Single entry point for all MCP tool calls |
| MCP Client | `backend/app/mcp/clients.py` | HTTP transport to external MCP servers |
| Tool Map | `backend/app/mcp/tool_map.py` | Maps logical tool names to MCP server tool names |
| Guardrails | `backend/app/guardrails.py` | Pre/post validation on MCP and file operations |
| Config Loader | `backend/app/config_loader.py` | Loads and validates YAML policy |
| Workflow Store | `backend/app/store.py` | JSON persistence for workflows and audit data |
| Terminal Runner | `backend/app/terminal_runner.py` | Runs configured validation commands in the target repo |

---

## End-to-End Pipeline

| Step | State | Agent / Component | Integration |
|---|---|---|---|
| 1 | `ANALYZING` | Jira MCP `fetch_issue` | Read ticket |
| 2 | `ANALYZING` | TaskAnalyzerAgent | Structure requirement |
| 3 | `ANALYZING` | ComplexityAgent | Score complexity 1–10 |
| 4 | `ANALYZING` | ModelSelectorAgent | Pick model tier |
| 5 | `PLANNING` | Git MCP `analyze` + PlanningAgent | Repo context + plan |
| 6 | `IMPLEMENTING` | Git MCP `branch` + ImplementationAgent | Branch + LLM code gen |
| 7 | `IMPLEMENTING` | Git MCP `write` | Write generated files |
| 8 | `VALIDATING` | ValidatorAgent + TerminalRunner | compileall, pytest, etc. |
| 9 | `RETRYING` (optional) | Orchestrator | Re-run with escalated model |
| 10 | `AWAITING_REVIEW` (optional) | User approve | Only if `review_required` |
| 11 | `PUBLISHING` | PublisherAgent | Git push + PR, Jira update |
| 12 | `COMPLETED` | ReportAgent | Final report |

---

## MCP Integration

### Design rules

- Sub-agents **never** call MCP directly; only `MCPAdapter` does.
- Tool names are **logical** in code (`fetch_issue`, `push`) and mapped to real MCP tool names in `policy.yaml`.
- Every call is tagged with a **stage** (`analyzing`, `implementing`, `publishing`) for guardrail allowlists.
- Requests and responses are **audited** with secrets redacted.

### Logical tools

**Jira MCP** (`mcp.jira.tools` in `policy.yaml`):

| Logical key | Default MCP name | When used |
|---|---|---|
| `fetch_issue` | `get_issue` | Start of pipeline |
| `transition` | `transition_issue` | After PR created |
| `comment` | `add_comment` | Post PR link to Jira |

**Git MCP** (`mcp.git.tools`):

| Logical key | Default MCP name | When used |
|---|---|---|
| `analyze` | `analyze_repository` | Before planning |
| `branch` | `create_branch` | Before implementation |
| `write` | `write_files` | After LLM generates code |
| `push` | `push_branch` | Publish phase |
| `pr` | `create_pull_request` | Publish phase |

### MCP call flow

```
Agent requests action
    → Guardrails.validate_request(stage, tool, arguments)
    → ExternalMCPClient.call_tool(server, tool_name, arguments)
    → Guardrails.validate_response(tool, response)
    → MCPAuditRecord appended to workflow
    → Result returned to agent
```

On guardrail failure: HTTP 422, workflow-safe error message, audit entry with `status: blocked`.

---

## Agents

All agents live under `backend/app/agents/`. Behavior is driven by `backend/config/agents.yaml` and prompt templates in `backend/config/prompts/`.

### TaskAnalyzerAgent

- **Input:** Jira task (summary, description, acceptance criteria)
- **Output:** Structured requirement, constraints, ambiguities
- **Rules:** Default acceptance criteria and ambiguity messages come from config; no LLM required

### ComplexityAgent

- **Input:** Jira task text
- **Output:** Score (1–10), level (LOW / MEDIUM / HIGH), estimated files
- **Rules:** Starts at `base_score`; adds points per `keyword_rules` in config; maps score to level via `levels` thresholds

### ModelSelectorAgent

- **Input:** Complexity assessment, retry count
- **Output:** Provider, model name, max tokens, reason
- **Rules:** Selects the route from `policy.yaml` → `model_routing` where `complexity_min <= score <= complexity_max`. On retry with `retry_escalation: next_tier`, moves to the next route in the list.

### PlanningAgent

- **Input:** Jira task, repository analysis
- **Output:** Versioned plan (objective, steps, risks, test approach)
- **Rules:** Plan structure is generated from config; prompt template at `prompts/planning.txt`

### ImplementationAgent

- **Input:** Jira task, plan, repository analysis
- **Output:** Generated files (path + content), summary
- **Rules:** Uses LLM via `ModelGateway`; prompt from `prompts/implementation.txt`; max files from config; JSON-only response enforced

### ValidatorAgent

- **Input:** Workflow, repository path
- **Output:** Pass/fail, validation summary
- **Rules:** Delegates to `TerminalRunner`; runs commands from `policy.yaml` → `validation.commands`

### PublisherAgent

- **Input:** Workflow, repository path
- **Output:** Pull request metadata
- **Rules:** Git MCP push + PR; Jira MCP transition + comment using `jira_publish.comment_template`

### ReportAgent

- **Input:** Completed workflow
- **Output:** Final report (Jira, complexity, model, validation, PR link, LLM key failover history)

---

## LLM gateway, failover, JSON, and discovery

### ModelGateway (`backend/app/llm.py`)

- Resolves an ordered **API key chain** from `policy.yaml` → `llm_key_chain` (secrets via `.env` / `Settings`).
- Workflow LLM calls use `FailoverLLMProvider` when at least one chain key resolves.
- **Failover reasons:** invalid key (401/403), rate limit / quota (429, 402), timeout, provider unavailable (5xx), model not found (404 model errors).
- **Not failover:** malformed JSON, HTTP 400 tool-choice conflicts, generic client errors.
- On failover: same stage and prompt are retried with the next key; `llm_failover_history`, `llm_keys_used`, and `audit_log` (`key_failover`) are persisted on the workflow.
- **1s pause** before trying the next key after rate-limit / quota failures.
- Cross-provider chain entries use `default_model_for()` for the target provider when the route provider differs.

### JSON parsing (`backend/app/llm_json.py`)

- Shared `parse_llm_json_object()` for implementation, planning, and complexity agents.
- Strips markdown fences and extracts the first JSON object when models wrap output in prose.

### Groq tool output

- Chat responses may return `tool_calls[].function.arguments`; GroqProvider treats that string as model text when `content` is empty.
- OSS `reasoning_effort` is not sent (reduces tool-choice 400 errors).

### Validation retry vs key failover

- **Key failover:** rotates API keys within one LLM request (`FailoverLLMProvider`).
- **Validation retry:** unchanged — `retry_count` and `ModelSelectorAgent.route_for_retry()` escalate model tier on validation failure.

### Model discovery API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/llm/providers/{provider}/models` | Lists models (Groq: live `GET /openai/v1/models`) |
| GET | `/api/llm/configuration` | Configured models, routing table, resolved key chain ids (no secrets) |

**Discovery response shape:**

```json
{
  "provider": "groq",
  "models": [
    { "provider": "groq", "id": "llama-3.3-70b-versatile", "display_name": "...", "owned_by": "...", "active": true }
  ]
}
```

The studio UI **LLM configuration** panel calls these endpoints and shows routing and discovered models in tables.

---

## Guardrails

Guardrails implement a **RAIL-style** policy layer around MCP and generated artifacts. Configuration: `policy.yaml` → `guardrails`.

### Pre-request checks (`validate_request`)

| Check | Description |
|---|---|
| **Stage allowlist** | Tool must be permitted for the current stage (e.g. `git.push` only in `publishing`) |
| **Prompt injection** | Blocks arguments containing patterns like "ignore previous instructions" |
| **Path safety** | Rejects absolute paths, `..`, and blocked segments (`.git`, `.env`, `node_modules`, `.venv`) |

### Post-response checks (`validate_response`)

| Check | Description |
|---|---|
| **Schema validation** | File payloads must include `path` and `content` strings |
| **Size limit** | File content must not exceed `max_file_bytes` (default 102400) |
| **Path re-validation** | All returned file paths checked again |

### Stage tool allowlists (default)

```yaml
analyzing:
  - jira.fetch_issue
implementing:
  - git.analyze
  - git.branch
  - git.write
publishing:
  - git.push
  - git.pr
  - jira.transition
  - jira.comment
```

### Audit and redaction

Each MCP call produces an `MCPAuditRecord`:

- Timestamp, workflow ID, agent, server, tool, status, duration
- `request_redacted` / `response_redacted` (tokens, passwords, API keys stripped)
- `guardrail_result` when blocked

High-level pipeline events are also stored in `workflow.audit_log`.

---

## Automation Modes

Configured in `policy.yaml` → `automation`:

| Setting | Values | Effect |
|---|---|---|
| `mode` | `full` (default) | Fully automated through publish |
| `mode` | `review_required` | Pauses at `AWAITING_REVIEW`; user must approve before publish |
| `auto_start` | `true` | `POST /api/workflows` immediately runs the pipeline |
| `max_retries` | number (default 2) | Max re-implementation attempts after validation failure |
| `retry_on` | list | e.g. `validation_fail`, `implementation_fail` |
| `retry_escalation` | `next_tier` | Use next model route on retry |

---

## Configuration Files

| File | Purpose |
|---|---|
| `backend/.env` | Secrets: MCP URLs/tokens, Gemini key, repo path, transition ID |
| `backend/config/policy.yaml` | Automation, model routing, MCP tool map, validation, guardrails, Jira publish template |
| `backend/config/agents.yaml` | Agent rules, complexity keywords, prompt template paths |
| `backend/config/ui.yaml` | Studio branding, theme, workflow stage labels |
| `backend/config/prompts/planning.txt` | Planning prompt template |
| `backend/config/prompts/implementation.txt` | Implementation prompt template |

Environment variables referenced in YAML use `${VAR_NAME}` syntax and are resolved at load time from `.env` / process environment.

---

## Workflow States

```
NEW → RUNNING → ANALYZING → PLANNING → IMPLEMENTING → VALIDATING
  → COMPLETED | FAILED | RETRYING | AWAITING_REVIEW → PUBLISHING → COMPLETED
```

| State | Meaning |
|---|---|
| `RUNNING` | Pipeline started |
| `RETRYING` | Re-attempt after validation failure with escalated model |
| `AWAITING_REVIEW` | Validation passed; waiting for human approve (review mode only) |
| `PUBLISHING` | Git push/PR and Jira update in progress |
| `COMPLETED` | PR created, Jira updated, report generated |
| `FAILED` | Unrecoverable error or retry limit reached |

---

## Model Routing

Defined in `policy.yaml` → `model_routing`. Model names resolve from `.env`:

| Complexity | Env variable | Typical model |
|---|---|---|
| 1–3 (LOW) | `GEMINI_MODEL_LOW` | Smallest/fastest |
| 4–6 (MEDIUM) | `GEMINI_MODEL_MEDIUM` | Balanced |
| 7–10 (HIGH) | `GEMINI_MODEL_HIGH` | Strongest |

The orchestrator sets `workflow.selected_model` to `{provider}:{model}`. No user-facing model picker exists; selection is automatic.

---

## API Surface

| Endpoint | Purpose |
|---|---|
| `GET /health` | MCP, model, repository readiness |
| `GET /api/config/public` | UI theme and stage labels (no secrets) |
| `POST /api/workflows` | Create workflow; auto-runs if `auto_start: true` |
| `POST /api/workflows/{id}/run` | Start or restart pipeline |
| `POST /api/workflows/{id}/approve` | Publish after review (review mode only) |
| `GET /api/workflows/{id}` | Full workflow state for AIDLC Studio UI |
| `GET /api/workflows/{id}/files/{path}` | Generated file content for editor |
| `GET /api/workflows/{id}/report` | Final report |

---

## Frontend: AIDLC Studio

The React UI (`frontend/src/components/`) presents an IDE-style workspace:

- **Command bar** — Jira key input, Run Pipeline, integration health
- **Workflow progress** — Config-driven stage rail from `ui.yaml`
- **File explorer** — Generated/changed files
- **Monaco editor** — Read-only syntax-highlighted code view
- **Terminal dock** — Validation command output
- **Agent activity** — Pipeline events + MCP audit stream
- **Completion card** — PR link or review/ failure state

Theme tokens are loaded from `/api/config/public` and applied as CSS variables.

---

## Security Notes

- Secrets live in `.env` only; never in YAML values committed to source control.
- MCP audit records redact `auth_token`, `password`, `api_key`, and similar fields.
- Guardrails block writes to sensitive paths and oversize generated files.
- Prompt-injection patterns in Jira-sourced text are filtered before use in MCP/LLM arguments.
- CORS origins are configurable via `CORS_ORIGINS`.

---

## Extending the Platform

To add a new integration:

1. Expose tools on an external MCP server.
2. Map logical tool names in `policy.yaml` → `mcp.<server>.tools`.
3. Add stage allowlist entries under `guardrails.stage_tools`.
4. Call through `MCPAdapter` from the relevant agent — do not bypass the adapter.

To add a new agent:

1. Create a module under `backend/app/agents/`.
2. Register behavior in `agents.yaml`.
3. Invoke from `Orchestrator.run()` at the appropriate state transition.

To change automation behavior:

1. Edit `policy.yaml` (mode, retries, validation commands, model routes).
2. Restart the API — config is loaded at startup.

---

## Related Documentation

- [README.md](README.md) — Quick start and run instructions
- [backend/.env.example](backend/.env.example) — Environment variable reference
- [backend/config/policy.yaml](backend/config/policy.yaml) — Primary runtime policy
