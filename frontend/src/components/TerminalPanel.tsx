import type { Workflow } from "../types";

type Props = {
  workflow?: Workflow;
};

export function TerminalPanel({ workflow }: Props) {
  const entries = workflow?.terminal_log ?? [];

  return (
    <section className="terminal-panel">
      <div className="panel-title">Terminal</div>
      <div className="terminal-body">
        {!entries.length && <p className="muted">Validation output will stream here.</p>}
        {entries.map((entry) => (
          <div key={`${entry.command_id}-${entry.duration_ms}`} className={`terminal-entry status-${entry.status.toLowerCase()}`}>
            <div className="terminal-meta">
              <span>{entry.command_id}</span>
              <span>{entry.status}</span>
              <span>{entry.duration_ms}ms</span>
            </div>
            <pre>{entry.command}</pre>
            <pre>{entry.output}</pre>
          </div>
        ))}
      </div>
    </section>
  );
}
