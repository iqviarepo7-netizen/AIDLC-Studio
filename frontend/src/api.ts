import type { BranchListResponse, HealthStatus, PublicConfig, SetupRequest, SetupResponse, Workflow, WorkflowReport } from "./types";
import type { CreateJiraAgentResponse, CreateJiraIssueResponse, JiraCreateMetadata, JiraIssueTypeOption, JiraProjectOption } from "./types/jiraCreate";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

let sessionId: string | undefined;

export function setSessionId(id: string | undefined) {
  sessionId = id;
}

export function getSessionId() {
  return sessionId;
}

function headers(): HeadersInit {
  const base: Record<string, string> = { "Content-Type": "application/json" };
  if (sessionId) base["X-Session-Id"] = sessionId;
  return base;
}

async function request<T>(path: string, method = "GET", body?: object): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : "The request could not be completed.");
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthStatus>("/health"),
  publicConfig: () => request<PublicConfig>("/api/config/public"),
  validateSetup: (payload: SetupRequest) => request<SetupResponse>("/api/setup/validate", "POST", payload),
  previewBranches: (repositoryPath: string) =>
    request<BranchListResponse>("/api/setup/branches", "POST", { repository_path: repositoryPath }),
  sessionConfig: () => request<SetupRequest>("/api/setup/session/config"),
  branches: () => request<BranchListResponse>("/api/repository/branches"),
  create: (jiraKey: string, baseBranch?: string) =>
    request<Workflow>("/api/workflows", "POST", { jira_key: jiraKey, base_branch: baseBranch }),
  run: (id: string) => request<Workflow>(`/api/workflows/${id}/run`, "POST"),
  selectModel: (id: string, routeId: string, workBranch?: string) =>
    request<Workflow>(`/api/workflows/${id}/model-selection`, "POST", { route_id: routeId, work_branch: workBranch }),
  get: (id: string) => request<Workflow>(`/api/workflows/${id}`),
  approve: (id: string) => request<Workflow>(`/api/workflows/${id}/approve`, "POST", { approved: true }),
  resume: (id: string) => request<Workflow>(`/api/workflows/${id}/resume`, "POST"),
  proceedPlan: (id: string) => request<Workflow>(`/api/workflows/${id}/proceed-plan`, "POST"),
  regeneratePlan: (id: string) => request<Workflow>(`/api/workflows/${id}/regenerate-plan`, "POST"),
  jiraSync: (id: string) => request<{ jira_comment_found: boolean; flow_complete: boolean; pr_url: string; jira_key: string }>(`/api/workflows/${id}/jira-sync`),
  report: (id: string) => request<{ status: string; workflow: Workflow; report?: WorkflowReport | null }>(`/api/workflows/${id}/report`),
  file: async (id: string, path: string) => {
    const response = await fetch(`${API}/api/workflows/${id}/files/${encodeURIComponent(path)}`, { headers: headers() });
    if (!response.ok) throw new Error("Could not load file content.");
    return response.text();
  },
  subscribeWorkflow: (id: string, onUpdate: (workflow: Workflow) => void) => {
    const source = new EventSource(`${API}/api/workflows/${id}/events`);
    source.onmessage = (event) => onUpdate(JSON.parse(event.data) as Workflow);
    return () => source.close();
  },
  jiraCreateProjects: () => request<{ projects: JiraProjectOption[] }>("/api/jira/create/projects"),
  jiraCreateIssueTypes: (projectId: string) =>
    request<{ issue_types: JiraIssueTypeOption[] }>(`/api/jira/create/issue-types?project_id=${encodeURIComponent(projectId)}`),
  jiraCreateMetadata: (projectId: string, issueTypeId: string) =>
    request<JiraCreateMetadata>("/api/jira/create/metadata", "POST", { project_id: projectId, issue_type_id: issueTypeId }),
  jiraCreateUserSearch: (projectId: string, query = "") =>
    request<{ users: { label: string; value: string }[] }>(
      `/api/jira/create/user-search?project_id=${encodeURIComponent(projectId)}&query=${encodeURIComponent(query)}`,
    ),
  jiraCreateIssueSearch: (projectId: string, query = "") =>
    request<{ issues: { label: string; value: string }[] }>(
      `/api/jira/create/issue-search?project_id=${encodeURIComponent(projectId)}&query=${encodeURIComponent(query)}`,
    ),
  jiraCreateIssueLinkTypes: () => request<{ link_types: import("./types/jiraCreate").JiraIssueLinkTypeOption[] }>("/api/jira/create/issue-link-types"),
  jiraCreateIssue: (payload: {
    project_id: string;
    issue_type_id: string;
    fields: Record<string, unknown>;
    issue_links?: import("./types/jiraCreate").CreateJiraIssueLinkRequest[];
  }) => request<CreateJiraIssueResponse>("/api/jira/create/issue", "POST", payload),
  jiraCreateIssueAttachments: async (issueKey: string, files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("uploads", file));
    const response = await fetch(`${API}/api/jira/create/issue/${encodeURIComponent(issueKey)}/attachments`, {
      method: "POST",
      headers: sessionId ? { "X-Session-Id": sessionId } : undefined,
      body: form,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === "string" ? error.detail : "Could not upload Jira attachments.");
    }
    return response.json() as Promise<import("./types/jiraCreate").CreateJiraAttachmentResponse>;
  },
  jiraCreateAgent: (payload: {
    messages: { role: "user" | "assistant"; content: string }[];
    project_id: string;
    issue_type_id: string;
    project_label?: string;
    issue_type_label?: string;
    current_values: Record<string, unknown>;
    user_edited_field_ids: string[];
  }) => request<CreateJiraAgentResponse>("/api/jira/create/agent", "POST", payload),
};
