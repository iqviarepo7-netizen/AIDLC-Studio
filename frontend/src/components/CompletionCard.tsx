import { useEffect, useState } from "react";
import type { Workflow } from "../types";

type Props = {
  workflow?: Workflow;
  onApprove?: () => void;
  onResume?: () => void;
  onCheckJira?: () => Promise<boolean>;
  onDeliveryComplete?: () => void;
  busy?: boolean;
};

export function CompletionCard({ workflow, onApprove, onResume, onCheckJira, onDeliveryComplete, busy }: Props) {
  const [modalOpen, setModalOpen] = useState(true);
  const [jiraVerified, setJiraVerified] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string>();
  const [closingIn, setClosingIn] = useState<number | null>(null);

  useEffect(() => {
    setModalOpen(true);
    setJiraVerified(false);
    setSyncMessage(undefined);
    setClosingIn(null);
  }, [workflow?.id, workflow?.state]);

  useEffect(() => {
    if (!jiraVerified) return;
    onDeliveryComplete?.();
    setClosingIn(3);
    const timer = window.setInterval(() => {
      setClosingIn((current) => {
        if (current === null || current <= 1) {
          window.clearInterval(timer);
          setModalOpen(false);
          return null;
        }
        return current - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [jiraVerified, onDeliveryComplete]);

  if (!workflow) return null;

  const handleRefresh = async () => {
    if (!onCheckJira) return;
    setSyncMessage(undefined);
    const ok = await onCheckJira();
    setJiraVerified(ok);
    setSyncMessage(ok ? "Jira comment found. Delivery flow completed." : "PR comment not found on Jira yet. Merge the PR, then refresh again.");
  };

  if (workflow.state === "AWAITING_REVIEW") {
    return (
      <section className="completion-card review">
        <h2>Review required before publish</h2>
        <p>Validation passed. Approve to publish the branch, create the PR, and update Jira via MCP.</p>
        <button onClick={onApprove} disabled={busy}>Approve and Publish</button>
      </section>
    );
  }

  if (workflow.state === "COMPLETED" && workflow.pull_request) {
    return (
      <>
        <section className="completion-card success">
          <h2>Pipeline completed</h2>
          <p>{workflow.report?.summary ?? workflow.jira_task?.summary}</p>
          <a href={workflow.pull_request.url} target="_blank" rel="noreferrer">
            Open PR #{workflow.pull_request.number}
          </a>
        </section>
        {modalOpen && (
          <div className="completion-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="completion-title">
            <div className="completion-modal">
              <div className="completion-modal-head">
                <div>
                  <p className="eyebrow">Pull request ready</p>
                  <h2 id="completion-title">{jiraVerified ? "Delivery flow completed" : `PR #${workflow.pull_request.number} created`}</h2>
                </div>
                <button type="button" className="ghost small" onClick={() => setModalOpen(false)}>
                  Close
                </button>
              </div>
              {!jiraVerified ? (
                <>
                  <p className="muted">
                    Merge the PR when ready, then refresh to confirm the Jira comment is visible. The delivery flow completes when the PR link appears in Jira comments.
                  </p>
                  <div className="completion-modal-actions">
                    <a className="modal-link" href={workflow.pull_request.url} target="_blank" rel="noreferrer">
                      Open PR #{workflow.pull_request.number}
                    </a>
                    <button type="button" onClick={handleRefresh} disabled={busy}>
                      Refresh Jira status
                    </button>
                  </div>
                  {syncMessage && <p className="warning-text">{syncMessage}</p>}
                </>
              ) : (
                <>
                  <p className="status-pass">{syncMessage ?? "Jira comment found. Delivery flow completed."}</p>
                  <p className="muted">Closing automatically in {closingIn ?? 3}s. You can close now if you prefer.</p>
                  <div className="completion-modal-actions">
                    <a className="modal-link" href={workflow.pull_request.url} target="_blank" rel="noreferrer">
                      Open PR #{workflow.pull_request.number}
                    </a>
                    <button type="button" onClick={() => setModalOpen(false)}>
                      Close now
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </>
    );
  }

  if (workflow.state === "FAILED") {
    return (
      <section className="completion-card error">
        <h2>Pipeline failed</h2>
        <p>{workflow.error ?? "The workflow did not complete successfully."}</p>
        {workflow.current_stage && <p className="muted">Stopped at: {workflow.current_stage}</p>}
        <div className="completion-actions">
          <button onClick={onResume} disabled={busy}>Continue from here</button>
        </div>
      </section>
    );
  }

  return null;
}
