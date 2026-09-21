import { useEffect, useMemo, useState } from "react";
import type { Workflow } from "../types";

type Props = {
  workflow?: Workflow;
  busy?: boolean;
  onProceedPlan?: () => void;
  onRegeneratePlan?: () => void;
};

function useTypewriter(text: string, active: boolean, speed = 16) {
  const [visible, setVisible] = useState("");
  useEffect(() => {
    if (!active) {
      setVisible(text);
      return;
    }
    setVisible("");
    let index = 0;
    const timer = window.setInterval(() => {
      index += 1;
      setVisible(text.slice(0, index));
      if (index >= text.length) window.clearInterval(timer);
    }, speed);
    return () => window.clearInterval(timer);
  }, [text, active, speed]);
  return visible;
}

function PlanReviewPanel({ workflow, busy, onProceedPlan, onRegeneratePlan }: Props) {
  const plan = workflow?.plans[0];
  const [held, setHeld] = useState(false);
  const [seconds, setSeconds] = useState(10);
  const body = useMemo(
    () => [plan?.objective ?? "", ...(plan?.implementation_steps ?? []).map((step, index) => `${index + 1}. ${step}`)].join("\n"),
    [plan],
  );
  const typed = useTypewriter(body, Boolean(plan));

  useEffect(() => {
    setHeld(false);
    setSeconds(10);
  }, [workflow?.id, plan?.version]);

  useEffect(() => {
    if (!plan || held || busy) return;
    if (seconds <= 0) {
      onProceedPlan?.();
      return;
    }
    const timer = window.setTimeout(() => setSeconds((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [plan, held, busy, seconds, onProceedPlan]);

  if (!plan) return null;

  return (
    <section
      className="stage-card plan-stage"
      onMouseDown={() => setHeld(true)}
      onMouseUp={() => setHeld(false)}
      onMouseLeave={() => setHeld(false)}
      onTouchStart={() => setHeld(true)}
      onTouchEnd={() => setHeld(false)}
    >
      <div className="stage-card-head">
        <p className="eyebrow stage-pulse">Implementation plan</p>
        <span className="stage-timer">{held ? "Paused — release to resume" : `Auto-build in ${seconds}s`}</span>
      </div>
      <pre className="plan-typewriter">{typed}</pre>
      {plan.risks?.[0] && <p className="warning-text">{plan.risks[0]}</p>}
      <div className="stage-card-actions">
        <button type="button" onClick={onProceedPlan} disabled={busy}>
          Proceed with plan
        </button>
        <button type="button" className="ghost" onClick={onRegeneratePlan} disabled={busy}>
          Regenerate plan
        </button>
      </div>
    </section>
  );
}

export function StageActivityCard({ workflow, busy, onProceedPlan, onRegeneratePlan }: Props) {
  if (!workflow) return null;

  if (workflow.current_stage === "plan_review" && workflow.plans[0]) {
    return <PlanReviewPanel workflow={workflow} busy={busy} onProceedPlan={onProceedPlan} onRegeneratePlan={onRegeneratePlan} />;
  }

  if (workflow.state === "PLANNING") {
    return (
      <section className="stage-card shimmer-stage">
        <p className="eyebrow stage-pulse">Planning</p>
        <h2>Drafting the implementation plan</h2>
        <ul className="stage-checklist">
          <li className="done">Issue understood</li>
          <li className="active">Mapping files and steps</li>
          <li>Waiting for your review</li>
        </ul>
      </section>
    );
  }

  if (workflow.state === "RUNNING" || workflow.state === "ANALYZING" || workflow.state === "RETRYING") {
    return (
      <section className="stage-card analyze-stage">
        <p className="eyebrow stage-pulse">Analyze</p>
        <h2>Agents are studying the ticket and repository</h2>
        <ul className="stage-checklist">
          <li className={workflow.jira_task ? "done" : "active"}>Fetch Jira issue</li>
          <li className={workflow.scope_analysis ? "done" : workflow.jira_task ? "active" : ""}>Scope repository patterns</li>
          <li className={workflow.complexity ? "done" : workflow.scope_analysis ? "active" : ""}>Score complexity</li>
        </ul>
        {workflow.jira_task && (
          <dl className="jira-meta">
            <div>
              <dt>Status</dt>
              <dd>{workflow.jira_task.status ?? "Unknown"}</dd>
            </div>
            <div>
              <dt>Assignee</dt>
              <dd>{workflow.jira_task.assignee ?? "Unassigned"}</dd>
            </div>
            <div>
              <dt>Type</dt>
              <dd>{workflow.jira_task.issue_type ?? "Task"}</dd>
            </div>
            <div>
              <dt>Priority</dt>
              <dd>{workflow.jira_task.priority ?? "None"}</dd>
            </div>
          </dl>
        )}
      </section>
    );
  }

  if (workflow.state === "IMPLEMENTING") {
    const files = workflow.generated_files;
    return (
      <section className="stage-card build-stage">
        <p className="eyebrow stage-pulse">Build</p>
        <h2>{files.length ? "Writing generated files" : "Generating code with the selected model"}</h2>
        {files.length ? (
          <ul className="stage-file-list">
            {files.map((file, index) => (
              <li key={file.path} className="file-ready" style={{ animationDelay: `${index * 120}ms` }}>
                Updated · {file.path}
              </li>
            ))}
          </ul>
        ) : (
          <div className="stage-orbit" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        )}
      </section>
    );
  }

  if (workflow.state === "VALIDATING") {
    const command = workflow.test_result?.executed_command ?? workflow.terminal_log.at(-1)?.command ?? "pytest";
    return (
      <section className="stage-card test-stage">
        <p className="eyebrow stage-pulse">Test</p>
        <h2>Running validation in the workspace</h2>
        <code className="stage-command">{command}</code>
        {workflow.terminal_log.at(-1)?.output && <pre className="stage-terminal-preview">{workflow.terminal_log.at(-1)?.output.slice(-600)}</pre>}
      </section>
    );
  }

  if (workflow.state === "PUBLISHING") {
    return (
      <section className="stage-card publish-stage">
        <p className="eyebrow stage-pulse">Publish</p>
        <h2>Opening pull request and syncing delivery artifacts</h2>
        <div className="stage-orbit" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </section>
    );
  }

  return null;
}
