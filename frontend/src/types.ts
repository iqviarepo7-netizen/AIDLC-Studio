export type TerminalLogEntry = {
  command_id: string;
  command: string;
  status: string;
  output: string;
  duration_ms: number;
};

export type MCPAuditRecord = {
  timestamp: string;
  workflow_id: string;
  agent: string;
  server: string;
  tool: string;
  status: string;
  duration_ms: number;
  guardrail_result?: string | null;
};

export type GeneratedFile = {
  path: string;
  content: string;
};

export type Workflow = {
  id: string;
  jira_key: string;
  state: string;
  error?: string | null;
  current_stage?: string | null;
  retry_count: number;
  selected_base_branch?: string | null;
  work_branch?: string | null;
  jira_task?: { key: string; summary: string; description?: string } | null;
  requirement_analysis?: { functional_requirement: string; ambiguities: string[] } | null;
  scope_analysis?: {
    change_type: string;
    pattern_summary: string;
    already_implemented: boolean;
    already_implemented_reason?: string | null;
    related_files: string[];
  } | null;
  branch_analysis?: {
    base_branch: string;
    suggested_work_branch: string;
    existing_branches: string[];
    branch_collision: boolean;
    collision_message?: string | null;
  } | null;
  complexity?: { score: number; level: string; explanation: string } | null;
  model_recommendation?: {
    recommended_model_id: string;
    reason: string;
    alternatives: { id: string; label: string; provider: string; model: string; available: boolean; recommended: boolean; estimated_tokens: number }[];
  } | null;
  model_selection?: { provider: string; model: string; reason: string } | null;
  selected_model?: string | null;
  plans: { version: number; objective: string; implementation_steps: string[]; change_request?: string | null; risks?: string[] }[];
  generated_files: GeneratedFile[];
  implementation?: { branch: string; changed_files: string[]; diff_summary: string; validation_status: string; validation_summary: string } | null;
  test_result?: { status: string; summary: string; passed: number; failed: number; executed_command: string } | null;
  pull_request?: { title: string; url: string; number: number } | null;
  terminal_log: TerminalLogEntry[];
  mcp_audit: MCPAuditRecord[];
  audit_log: { timestamp: string; agent: string; action: string; status: string }[];
  report?: { jira_key: string; summary: string; pr_url?: string | null; final_status: string } | null;
};

export type PublicConfig = {
  app: { name: string; tagline: string };
  theme: Record<string, string>;
  stages: { id: string; label: string }[];
  automation_mode: string;
  require_model_selection: boolean;
  default_base_branch?: string;
};

export type BranchListResponse = {
  branches: string[];
  default_branch: string;
};

export type HealthStatus = {
  status: string;
  automation_mode: string;
  mcp: { jira_configured: boolean; git_configured: boolean };
  repository_configured: boolean;
  gemini_configured: boolean;
  groq_configured?: boolean;
  session_active?: boolean;
};

export type JiraConnectionConfig = {
  mode: "direct" | "mcp";
  base_url?: string;
  email?: string;
  api_token?: string;
  mcp_url?: string;
  mcp_token?: string;
  transition_id?: string;
};

export type GitConnectionConfig = {
  mode: "direct" | "mcp";
  repository_path?: string;
  base_branch?: string;
  remote?: string;
  mcp_url?: string;
  mcp_token?: string;
};

export type SetupRequest = {
  jira: JiraConnectionConfig;
  git: GitConnectionConfig;
};

export type SetupResponse = {
  session_id: string;
  jira: { ok: boolean; mode: string; message: string };
  git: { ok: boolean; mode: string; message: string };
  branches: string[];
  default_branch: string;
  summary: {
    jira_mode: string;
    git_mode: string;
    repository_path?: string | null;
    jira_host?: string | null;
    default_base_branch?: string | null;
  };
};

export type SetupSummary = SetupResponse["summary"];
