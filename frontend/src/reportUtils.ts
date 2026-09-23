import type { Workflow, WorkflowReport } from "./types";

export type SectionStatus = "completed" | "failed" | "not_reached" | "pending";

const SECTION_DEFS: { id: string; label: string }[] = [
  { id: "requirement", label: "Requirement Analysis" },
  { id: "planning", label: "Planning & Model Selection" },
  { id: "build", label: "Implementation" },
  { id: "testing", label: "Testing & Validation" },
  { id: "delivery", label: "PR & Jira Delivery" },
];

const STAGE_TO_SECTION: Record<string, string> = {
  fetch_issue: "requirement",
  plan: "planning",
  plan_review: "planning",
  implement: "build",
  validate: "testing",
  publish: "delivery",
};

const STAGE_LABELS: Record<string, string> = {
  fetch_issue: "Analyze",
  plan: "Plan",
  plan_review: "Plan",
  implement: "Build",
  validate: "Test",
  publish: "Publish",
};

function sectionHasContent(workflow: Workflow, sectionId: string): boolean {
  if (sectionId === "requirement") return Boolean(workflow.jira_task);
  if (sectionId === "planning") return Boolean(workflow.plans.length || workflow.complexity || workflow.model_selection);
  if (sectionId === "build") return Boolean(workflow.generated_files.length || workflow.implementation);
  if (sectionId === "testing") return Boolean(workflow.terminal_log.length || workflow.test_result || workflow.implementation);
  if (sectionId === "delivery") return Boolean(workflow.pull_request);
  return false;
}

export function canShowReport(workflow?: Workflow): boolean {
  if (!workflow) return false;
  if (workflow.pull_request || workflow.state === "COMPLETED") return true;
  if (workflow.state === "FAILED" && workflow.jira_task) return true;
  return false;
}

export function isPartialReport(workflow: Workflow): boolean {
  return workflow.report?.report_status === "partial" || workflow.state === "FAILED";
}

export function getSectionStatuses(workflow: Workflow, report?: WorkflowReport | null): { id: string; label: string; status: SectionStatus }[] {
  if (report?.sections?.length) {
    return report.sections.map((section) => ({
      id: section.id,
      label: section.label,
      status: section.status as SectionStatus,
    }));
  }

  const isFailed = workflow.state === "FAILED";
  const failedSection = STAGE_TO_SECTION[workflow.current_stage ?? ""] ?? "";
  const failedIndex = SECTION_DEFS.findIndex((section) => section.id === failedSection);

  return SECTION_DEFS.map((section, index) => {
    let status: SectionStatus;
    if (isFailed && section.id === failedSection) {
      status = "failed";
    } else if (isFailed && failedIndex >= 0 && index > failedIndex) {
      status = "not_reached";
    } else if (sectionHasContent(workflow, section.id)) {
      status = "completed";
    } else if (isFailed) {
      status = "not_reached";
    } else {
      status = "pending";
    }
    return { ...section, status };
  });
}

export function getFailureInfo(workflow: Workflow, report?: WorkflowReport | null) {
  if (report?.failure) return report.failure;
  if (workflow.state !== "FAILED") return null;
  const failedAgent = [...(workflow.audit_log ?? [])].reverse().find((entry) => entry.status === "failed")?.agent;
  return {
    stage: workflow.current_stage ?? undefined,
    stage_label: STAGE_LABELS[workflow.current_stage ?? ""] ?? workflow.current_stage ?? undefined,
    error: workflow.error ?? undefined,
    agent: failedAgent,
  };
}

export function getSectionStatus(workflow: Workflow, sectionId: string, report?: WorkflowReport | null): SectionStatus {
  return getSectionStatuses(workflow, report).find((section) => section.id === sectionId)?.status ?? "pending";
}
