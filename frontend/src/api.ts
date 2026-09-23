import type { BranchListResponse, HealthStatus, PublicConfig, SetupRequest, SetupResponse, Workflow, WorkflowReport } from "./types";

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
};
