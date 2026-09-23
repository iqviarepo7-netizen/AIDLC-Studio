import { useState, type ReactNode } from "react";
import {
  getFailureInfo,
  getSectionStatus,
  getSectionStatuses,
  isPartialReport,
  type SectionStatus,
} from "../reportUtils";
import type { Workflow } from "../types";

type Props = {
  workflow: Workflow;
  onClose: () => void;
  onSelectFile?: (path: string) => void;
};

function formatDuration(ms?: number | null) {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

function truncate(text: string, max = 600) {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toUpperCase();
  const pass = normalized.includes("PASS") || normalized === "COMPLETED" || normalized === "SUCCESS";
  const fail = normalized.includes("FAIL") || normalized === "FAILED" || normalized === "ERROR";
  return <span className={`report-badge ${pass ? "pass" : fail ? "fail" : ""}`}>{status}</span>;
}

function SectionStatusBadge({ status }: { status: SectionStatus }) {
  const labels: Record<SectionStatus, string> = {
    completed: "Completed",
    failed: "Failed",
    not_reached: "Not reached",
    pending: "Pending",
  };
  return <span className={`report-section-badge ${status}`}>{labels[status]}</span>;
}

function ReportSection({
  title,
  status,
  defaultOpen = false,
  children,
}: {
  title: string;
  status: SectionStatus;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen || status === "failed");
  const blocked = status === "not_reached";

  return (
    <section className={`report-section ${open ? "open" : ""} section-${status}`}>
      <button type="button" className="report-section-toggle" onClick={() => setOpen((current) => !current)} aria-expanded={open}>
        <span>{title}</span>
        <div className="report-section-toggle-meta">
          <SectionStatusBadge status={status} />
          <em>{open ? "−" : "+"}</em>
        </div>
      </button>
      {open && (
        <div className="report-section-body">
          {blocked ? <p className="muted">Pipeline stopped before this stage was reached.</p> : children}
        </div>
      )}
    </section>
  );
}

function BulletList({ items }: { items: string[] }) {
  if (!items.length) return <p className="muted">None recorded.</p>;
  return (
    <ul className="report-list">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function ImplementationReportPanel({ workflow, onClose, onSelectFile }: Props) {
  const report = workflow.report;
  const partial = isPartialReport(workflow);
  const failure = getFailureInfo(workflow, report);
  const sectionStatuses = getSectionStatuses(workflow, report);

  const requirement = report?.requirement;
  const planning = report?.planning;
  const build = report?.build;
  const testing = report?.testing;
  const delivery = report?.delivery;

  const jiraTask = requirement?.jira_task ?? workflow.jira_task;
  const reqAnalysis = requirement?.requirement_analysis ?? workflow.requirement_analysis;
  const scope = requirement?.scope_analysis ?? workflow.scope_analysis;
  const repo = requirement?.repository_analysis ?? workflow.repository_analysis;
  const branch = requirement?.branch_analysis ?? workflow.branch_analysis;
  const plan = planning?.plan ?? workflow.plans[workflow.plans.length - 1];
  const pr = delivery?.pull_request ?? workflow.pull_request;
  const changedFiles = build?.changed_files ?? workflow.implementation?.changed_files ?? workflow.generated_files.map((file) => file.path);
  const fileSummaries = build?.files ?? workflow.generated_files.map((file) => ({ path: file.path, line_count: file.content.split("\n").length }));
  const terminalLog = testing?.terminal_log ?? workflow.terminal_log;
  const auditTrail = report?.audit_trail ?? workflow.mcp_audit;

  const durationMs =
    report?.duration_ms ??
    (workflow.created_at && workflow.updated_at
      ? new Date(workflow.updated_at).getTime() - new Date(workflow.created_at).getTime()
      : null);

  const requirementStatus = getSectionStatus(workflow, "requirement", report);
  const planningStatus = getSectionStatus(workflow, "planning", report);
  const buildStatus = getSectionStatus(workflow, "build", report);
  const testingStatus = getSectionStatus(workflow, "testing", report);
  const deliveryStatus = getSectionStatus(workflow, "delivery", report);

  return (
    <section className="report-panel">
      <div className="report-header">
        <div>
          <p className="eyebrow">{partial ? "Partial Implementation Report" : "Implementation Report"}</p>
          <h2 id="report-modal-title">
            {jiraTask?.key ?? workflow.jira_key}: {report?.summary ?? jiraTask?.summary ?? "Delivery summary"}
          </h2>
          <div className="report-meta-row">
            <StatusBadge status={report?.final_status ?? workflow.state} />
            {!partial && <StatusBadge status={report?.validation_status ?? workflow.implementation?.validation_status ?? "UNKNOWN"} />}
            {pr && <span className="report-meta-chip">PR #{pr.number}</span>}
            <span className="report-meta-chip">{formatDuration(durationMs)}</span>
            <span className="report-meta-chip">{report?.selected_model ?? workflow.selected_model ?? "unknown model"}</span>
            {(report?.retry_count ?? workflow.retry_count) > 0 && (
              <span className="report-meta-chip warn">{report?.retry_count ?? workflow.retry_count} retries</span>
            )}
          </div>
        </div>
        <button type="button" className="ghost small" onClick={onClose} aria-label="Close report">
          Close
        </button>
      </div>

      {partial && failure && (
        <div className="report-failure-banner">
          <h3>Pipeline failed at {failure.stage_label ?? failure.stage ?? "unknown stage"}</h3>
          <p>{failure.error ?? "The workflow did not complete successfully."}</p>
          {failure.agent && <p className="muted">Failed agent: {failure.agent}</p>}
        </div>
      )}

      {partial && sectionStatuses.length > 0 && (
        <div className="report-stage-track">
          {sectionStatuses.map((section) => (
            <div key={section.id} className={`report-stage-chip ${section.status}`}>
              <span>{section.label}</span>
            </div>
          ))}
        </div>
      )}

      <div className="report-links">
        {pr?.url && (
          <a href={pr.url} target="_blank" rel="noreferrer">
            Open PR #{pr.number}
          </a>
        )}
        {build?.work_branch && <span className="report-meta-chip mono">{build.work_branch}</span>}
      </div>

      <div className="report-sections">
        <ReportSection title="Requirement Analysis" status={requirementStatus} defaultOpen>
          <div className="report-grid">
            <div>
              <h4>Jira Issue</h4>
              <p>{jiraTask?.summary}</p>
              {jiraTask?.description && <p className="muted">{jiraTask.description}</p>}
              <div className="report-kv">
                {jiraTask?.issue_type && <span>Type: {jiraTask.issue_type}</span>}
                {jiraTask?.priority && <span>Priority: {jiraTask.priority}</span>}
              </div>
            </div>
            {reqAnalysis && (
              <div>
                <h4>Requirement Breakdown</h4>
                {reqAnalysis.problem_summary && <p>{reqAnalysis.problem_summary}</p>}
                <p className="muted">{reqAnalysis.functional_requirement}</p>
                <h5>Acceptance Criteria</h5>
                <BulletList items={reqAnalysis.acceptance_criteria ?? jiraTask?.acceptance_criteria ?? []} />
                <h5>Constraints</h5>
                <BulletList items={reqAnalysis.constraints ?? []} />
                <h5>Ambiguities</h5>
                <BulletList items={reqAnalysis.ambiguities ?? []} />
              </div>
            )}
            {scope && (
              <div>
                <h4>Scope Analysis</h4>
                <p>
                  <strong>{scope.change_type}</strong> — {scope.pattern_summary}
                </p>
                {scope.already_implemented && (
                  <p className="warning-text">Already implemented: {scope.already_implemented_reason ?? "Detected in repository."}</p>
                )}
                {scope.related_files.length > 0 && (
                  <>
                    <h5>Related Files</h5>
                    <BulletList items={scope.related_files} />
                  </>
                )}
              </div>
            )}
            {repo && (
              <div>
                <h4>Repository Context</h4>
                <div className="report-kv">
                  <span>Project: {repo.project_type}</span>
                  {repo.test_command && <span>Tests: {repo.test_command}</span>}
                </div>
                <h5>Relevant Directories</h5>
                <BulletList items={repo.relevant_directories} />
                <h5>Relevant Files</h5>
                <BulletList items={repo.relevant_files} />
                <p className="muted">{repo.notes}</p>
              </div>
            )}
            {branch && (
              <div>
                <h4>Branch Strategy</h4>
                <div className="report-kv">
                  <span>Base: {branch.base_branch}</span>
                  <span>Work: {branch.suggested_work_branch}</span>
                </div>
                {branch.branch_collision && branch.collision_message && <p className="warning-text">{branch.collision_message}</p>}
              </div>
            )}
          </div>
        </ReportSection>

        <ReportSection title="Planning & Model Selection" status={planningStatus}>
          <div className="report-grid">
            {(planning?.complexity ?? workflow.complexity) && (
              <div>
                <h4>Complexity</h4>
                <p>
                  {(planning?.complexity ?? workflow.complexity)!.level} ({(planning?.complexity ?? workflow.complexity)!.score}/10)
                </p>
                <p className="muted">{(planning?.complexity ?? workflow.complexity)!.explanation}</p>
              </div>
            )}
            {(planning?.model_recommendation ?? workflow.model_recommendation) && (
              <div>
                <h4>Model Recommendation</h4>
                <p>{(planning?.model_recommendation ?? workflow.model_recommendation)!.recommended_model_id}</p>
                <p className="muted">{(planning?.model_recommendation ?? workflow.model_recommendation)!.reason}</p>
              </div>
            )}
            {(planning?.model_selection ?? workflow.model_selection) && (
              <div>
                <h4>Selected Model</h4>
                <p>{planning?.selected_model ?? workflow.selected_model}</p>
                <p className="muted">{(planning?.model_selection ?? workflow.model_selection)!.reason}</p>
              </div>
            )}
            {plan && (
              <div className="report-span-2">
                <h4>Implementation Plan v{plan.version}</h4>
                <p>{plan.objective}</p>
                {plan.change_request && <p className="muted">{plan.change_request}</p>}
                <h5>Steps</h5>
                <BulletList items={plan.implementation_steps} />
                {plan.affected_components && plan.affected_components.length > 0 && (
                  <>
                    <h5>Affected Components</h5>
                    <BulletList items={plan.affected_components} />
                  </>
                )}
                {plan.likely_files && plan.likely_files.length > 0 && (
                  <>
                    <h5>Likely Files</h5>
                    <BulletList items={plan.likely_files} />
                  </>
                )}
                {plan.test_approach && plan.test_approach.length > 0 && (
                  <>
                    <h5>Test Approach</h5>
                    <BulletList items={plan.test_approach} />
                  </>
                )}
                {plan.risks && plan.risks.length > 0 && (
                  <>
                    <h5>Risks</h5>
                    <BulletList items={plan.risks} />
                  </>
                )}
                {plan.expected_result && (
                  <>
                    <h5>Expected Result</h5>
                    <p className="muted">{plan.expected_result}</p>
                  </>
                )}
              </div>
            )}
          </div>
        </ReportSection>

        <ReportSection title="Implementation" status={buildStatus}>
          {buildStatus === "failed" && failure?.error && (
            <div className="report-inline-failure">
              <StatusBadge status="FAILED" />
              <p>{failure.error}</p>
            </div>
          )}
          <div className="report-grid">
            <div>
              <h4>Branch</h4>
              <div className="report-kv">
                <span>Base: {build?.base_branch ?? workflow.selected_base_branch ?? "—"}</span>
                <span>Work: {build?.work_branch ?? workflow.work_branch ?? workflow.implementation?.branch ?? "—"}</span>
              </div>
              {(build?.collision_message ?? branch?.collision_message) && (
                <p className="warning-text">{build?.collision_message ?? branch?.collision_message}</p>
              )}
            </div>
            <div className="report-span-2">
              <h4>Change Summary</h4>
              <p>{build?.diff_summary ?? workflow.implementation?.diff_summary ?? (buildStatus === "failed" ? "Implementation did not complete." : "No diff summary recorded.")}</p>
            </div>
            <div className="report-span-2">
              <h4>Changed Files</h4>
              {fileSummaries.length > 0 || changedFiles.length > 0 ? (
                <ul className="report-file-list">
                  {fileSummaries.map((file) => (
                    <li key={file.path}>
                      <button type="button" className="report-file-link" onClick={() => onSelectFile?.(file.path)}>
                        {file.path}
                      </button>
                      <span className="muted">{file.line_count} lines</span>
                    </li>
                  ))}
                  {!fileSummaries.length && changedFiles.map((path) => <li key={path}>{path}</li>)}
                </ul>
              ) : (
                <p className="muted">No files were generated before the failure.</p>
              )}
            </div>
          </div>
        </ReportSection>

        <ReportSection title="Testing & Validation" status={testingStatus}>
          {testingStatus === "failed" && failure?.error && (
            <div className="report-inline-failure">
              <StatusBadge status="FAILED" />
              <p>{failure.error}</p>
            </div>
          )}
          <div className="report-grid">
            <div>
              <h4>Overall Status</h4>
              <StatusBadge status={testing?.validation_status ?? workflow.implementation?.validation_status ?? "UNKNOWN"} />
              {(testing?.test_result ?? workflow.test_result) && (
                <div className="report-kv">
                  <span>Passed: {(testing?.test_result ?? workflow.test_result)!.passed}</span>
                  <span>Failed: {(testing?.test_result ?? workflow.test_result)!.failed}</span>
                  <span>Command: {(testing?.test_result ?? workflow.test_result)!.executed_command}</span>
                </div>
              )}
            </div>
            {terminalLog.length > 0 && (
              <div className="report-span-2">
                <h4>Validation Commands</h4>
                <div className="report-command-table">
                  {terminalLog.map((entry) => (
                    <div key={`${entry.command_id}-${entry.command}`} className="report-command-row">
                      <StatusBadge status={entry.status} />
                      <code>{entry.command}</code>
                      <span className="muted">{entry.duration_ms}ms</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {(testing?.validation_summary ?? workflow.implementation?.validation_summary) && (
              <div className="report-span-2">
                <h4>Output Summary</h4>
                <pre className="report-pre">{truncate(testing?.validation_summary ?? workflow.implementation?.validation_summary ?? "", 1200)}</pre>
              </div>
            )}
          </div>
        </ReportSection>

        <ReportSection title="PR & Jira Delivery" status={deliveryStatus}>
          <div className="report-grid">
            {pr && (
              <div>
                <h4>Pull Request</h4>
                <p>
                  <a href={pr.url} target="_blank" rel="noreferrer">
                    #{pr.number}: {pr.title}
                  </a>
                </p>
                {"status" in pr && typeof pr.status === "string" && <StatusBadge status={pr.status} />}
              </div>
            )}
            <div>
              <h4>Jira Updates</h4>
              <div className="report-kv">
                <span className={delivery?.jira_comment_posted ? "status-pass" : "muted"}>
                  Comment posted: {delivery?.jira_comment_posted ? "Yes" : "Not confirmed"}
                </span>
                <span className={delivery?.jira_transition_posted ? "status-pass" : "muted"}>
                  Status transition: {delivery?.jira_transition_posted ? "Yes" : "No"}
                </span>
              </div>
            </div>
            {delivery?.pr_body && (
              <div className="report-span-2">
                <h4>PR Body</h4>
                <pre className="report-pre">{truncate(delivery.pr_body, 1200)}</pre>
              </div>
            )}
          </div>
        </ReportSection>

        {auditTrail.length > 0 && (
          <ReportSection title="Audit Trail" status="completed">
            <div className="report-audit-list">
              {auditTrail.map((entry) => (
                <div key={`${entry.timestamp}-${entry.tool}`} className="report-audit-row">
                  <span className="mono">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                  <strong>
                    {entry.agent} · {entry.server}.{entry.tool}
                  </strong>
                  <StatusBadge status={entry.status} />
                  <span className="muted">{entry.duration_ms}ms</span>
                </div>
              ))}
            </div>
          </ReportSection>
        )}
      </div>
    </section>
  );
}

export default ImplementationReportPanel;
