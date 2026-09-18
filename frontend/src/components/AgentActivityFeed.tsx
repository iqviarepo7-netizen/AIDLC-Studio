import type { Workflow } from "../types";

type Props = {
  workflow?: Workflow;
};

export function AgentActivityFeed({ workflow }: Props) {
  const audit = workflow?.mcp_audit ?? [];
  const activity = workflow?.audit_log ?? [];

  return (
    <aside className="agent-panel">
      <div className="panel-title">Agent Activity</div>
      <div className="feed-section">
        <h3>Pipeline</h3>
        <ul className="feed-list">
          {activity.map((event) => (
            <li key={`${event.timestamp}-${event.action}`}>
              <strong>{event.agent}</strong>
              <span>{event.action}</span>
              <em className={event.status === "failed" ? "status-fail" : event.status === "completed" ? "status-pass" : ""}>{event.status}</em>
            </li>
          ))}
        </ul>
      </div>
      <div className="feed-section">
        <h3>MCP Calls</h3>
        <ul className="feed-list">
          {audit.map((event) => (
            <li key={`${event.timestamp}-${event.tool}`}>
              <strong>{event.server}.{event.tool}</strong>
              <span className={event.status === "success" ? "status-pass" : event.status === "failed" || event.status === "error" ? "status-fail" : ""}>{event.status}</span>
              <em>{event.duration_ms}ms</em>
            </li>
          ))}
        </ul>
      </div>
      {workflow?.model_selection && (
        <div className="meta-block">
          <div className="panel-title">Model</div>
          <p>{workflow.selected_model}</p>
          <p className="muted">{workflow.model_selection.reason}</p>
        </div>
      )}
      {workflow?.plans[0] && (
        <div className="meta-block">
          <div className="panel-title">Plan</div>
          {workflow.plans[0].change_request && <p className="muted">{workflow.plans[0].change_request}</p>}
          {workflow.plans[0].risks?.[0] && <p className="warning-text">{workflow.plans[0].risks[0]}</p>}
        </div>
      )}
    </aside>
  );
}
