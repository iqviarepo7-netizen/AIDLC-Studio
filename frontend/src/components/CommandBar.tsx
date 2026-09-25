import type { HealthStatus, PublicConfig, SetupSummary } from "../types";

type Props = {
  config?: PublicConfig;
  health?: HealthStatus;
  sessionSummary?: SetupSummary;
  jiraKey: string;
  onJiraKeyChange: (value: string) => void;
  baseBranch: string;
  onStart: () => void;
  onCreateJira?: () => void;
  onReconfigure: () => void;
  busy: boolean;
  workflowState?: string;
  showReport?: boolean;
  reportPartial?: boolean;
  onViewReport?: () => void;
};

export function CommandBar({
  config,
  health,
  sessionSummary,
  jiraKey,
  onJiraKeyChange,
  baseBranch,
  onStart,
  onCreateJira,
  onReconfigure,
  busy,
  workflowState,
  showReport,
  reportPartial,
  onViewReport,
}: Props) {
  return (
    <header className="command-bar">
      <div className="brand">
        <div className="brand-mark">A</div>
        <div>
          <p className="eyebrow">{config?.app.tagline ?? "Agentic delivery workspace"}</p>
          <h1>{config?.app.name ?? "AIDLC Studio"}</h1>
          {sessionSummary && (
            <p className="session-meta">
              Jira {sessionSummary.jira_mode} · Git {sessionSummary.git_mode}
            </p>
          )}
        </div>
      </div>
      <div className="command-input">
        <label htmlFor="jira-key">Jira issue</label>
        <div className="command-row">
          <input
            id="jira-key"
            value={jiraKey}
            onChange={(event) => onJiraKeyChange(event.target.value.toUpperCase())}
            placeholder="PROJ-123"
            pattern="[A-Za-z][A-Za-z0-9_]*-[0-9]+"
          />
          <button onClick={onStart} disabled={busy || !jiraKey.trim() || (health?.repository_configured && !baseBranch)}>
            Run Pipeline
          </button>
          {onCreateJira && (
            <button type="button" onClick={onCreateJira} disabled={busy}>
              Create Jira
            </button>
          )}
        </div>
        <label htmlFor="base-branch">Base branch</label>
        <div className="command-row">
          <input id="base-branch" value={baseBranch} readOnly title="Change base branch from setup" />
        </div>
      </div>
      <div className="status-cluster">
        {showReport && onViewReport && (
          <button type="button" className={`report-trigger${reportPartial ? " partial" : ""}`} onClick={onViewReport}>
            {reportPartial ? "View Partial Report" : "View Report"}
          </button>
        )}
        <span className={`status-pill state-${(workflowState ?? "idle").toLowerCase()}`}>{workflowState ?? "Ready"}</span>
        <div className="health-tags">
          <span className={health?.session_active || health?.mcp.jira_configured ? "ok" : "warn"}>Jira</span>
          <span className={health?.repository_configured ? "ok" : "warn"}>Git</span>
          <span className={health?.gemini_configured || health?.groq_configured ? "ok" : "warn"}>Model</span>
        </div>
        <button className="ghost small" onClick={onReconfigure}>
          Change connections
        </button>
      </div>
    </header>
  );
}
