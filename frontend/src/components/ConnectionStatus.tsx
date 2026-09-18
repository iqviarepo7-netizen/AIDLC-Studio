import type { SetupResponse } from "../types";

type Props = {
  result: SetupResponse;
  onEnterStudio: () => void;
  onReconfigure: () => void;
};

export function ConnectionStatus({ result, onEnterStudio, onReconfigure }: Props) {
  return (
    <div className="connection-screen">
      <div className="connection-card">
        <p className="eyebrow">Session Ready</p>
        <h2>Connections validated</h2>
        <p className="muted">Configuration is active for this browser session. Refreshing the page will require setup again.</p>
        <div className="connection-grid">
          <article className={`connection-tile ${result.jira.ok ? "ok" : "fail"}`}>
            <h3>Jira · {result.jira.mode}</h3>
            <p>{result.jira.message}</p>
            {result.summary.jira_host && <small>{result.summary.jira_host}</small>}
          </article>
          <article className={`connection-tile ${result.git.ok ? "ok" : "fail"}`}>
            <h3>Git · {result.git.mode}</h3>
            <p>{result.git.message}</p>
            {result.summary.repository_path && <small>{result.summary.repository_path}</small>}
          </article>
        </div>
        {result.branches.length > 0 && (
          <p className="muted">
            Default base branch: <b>{result.default_branch}</b> · {result.branches.length} branches detected
          </p>
        )}
        <div className="connection-actions">
          <button onClick={onEnterStudio}>Open AIDLC Studio</button>
          <button className="ghost" onClick={onReconfigure}>
            Reconfigure
          </button>
        </div>
      </div>
    </div>
  );
}
