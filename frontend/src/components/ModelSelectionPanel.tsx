import type { Workflow } from "../types";

type Props = {
  workflow?: Workflow;
  selectedRoute?: string;
  workBranch: string;
  onWorkBranchChange: (value: string) => void;
  onSelectRoute: (routeId: string) => void;
  onConfirm: () => void;
  busy?: boolean;
};

export function ModelSelectionPanel({
  workflow,
  selectedRoute,
  workBranch,
  onWorkBranchChange,
  onSelectRoute,
  onConfirm,
  busy,
}: Props) {
  if (!workflow || workflow.state !== "MODEL_RECOMMENDED" || !workflow.model_recommendation) return null;

  const recommendation = workflow.model_recommendation;

  return (
    <section className="completion-card review">
      <h2>Select a model to generate code</h2>
      <p>{recommendation.reason}</p>
      {workflow.scope_analysis && (
        <div className="analysis-block">
          <p className="muted">
            Scope: <b>{workflow.scope_analysis.change_type.replaceAll("_", " ")}</b> — {workflow.scope_analysis.pattern_summary}
          </p>
          {workflow.scope_analysis.already_implemented && (
            <p className="warning-text">
              Possible duplicate work: {workflow.scope_analysis.already_implemented_reason ?? "Review before continuing."}
            </p>
          )}
        </div>
      )}
      {workflow.branch_analysis && (
        <div className="analysis-block branch-editor">
          <p className="muted">
            Base branch: <b>{workflow.branch_analysis.base_branch}</b>
          </p>
          <label htmlFor="work-branch">
            Work branch name
            <input
              id="work-branch"
              value={workBranch}
              onChange={(event) => onWorkBranchChange(event.target.value)}
              placeholder={workflow.branch_analysis.suggested_work_branch}
            />
          </label>
          {workflow.branch_analysis.branch_collision && workflow.branch_analysis.collision_message && (
            <p className="warning-text">{workflow.branch_analysis.collision_message}</p>
          )}
        </div>
      )}
      {workflow.complexity && (
        <p className="muted">
          Complexity: <b>{workflow.complexity.level}</b> · {workflow.complexity.score}/10 — {workflow.complexity.explanation}
        </p>
      )}
      <div className="model-options">
        {recommendation.alternatives.map((option) => (
          <label className={`model-option ${!option.available ? "disabled" : ""}`} key={option.id}>
            <input
              type="radio"
              value={option.id}
              checked={(selectedRoute ?? recommendation.recommended_model_id) === option.id}
              onChange={() => onSelectRoute(option.id)}
              disabled={!option.available}
            />
            <span>
              <b>{option.label}</b>
              {option.recommended ? " · recommended" : ""}
              <small>{option.estimated_tokens.toLocaleString()} estimated tokens</small>
            </span>
          </label>
        ))}
      </div>
      <button onClick={onConfirm} disabled={busy || !selectedRoute || !workBranch.trim()}>
        Continue with selected model
      </button>
    </section>
  );
}
