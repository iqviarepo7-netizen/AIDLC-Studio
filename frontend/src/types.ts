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
  jira_task?: { key: string; summary: string; description?: string; issue_type?: string; priority?: string | null; acceptance_criteria?: string[] } | null;
  requirement_analysis?: {
    problem_summary?: string;
    functional_requirement: string;
    acceptance_criteria?: string[];
    constraints?: string[];
    ambiguities: string[];
  } | null;
  repository_analysis?: {
    project_type: string;
    relevant_directories: string[];
    relevant_files: string[];
    test_command?: string | null;
    notes: string;
  } | null;
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
  plans: {
    version: number;
    objective: string;
    affected_components?: string[];
    likely_files?: string[];
    implementation_steps: string[];
    test_approach?: string[];
    risks?: string[];
    expected_result?: string;
    change_request?: string | null;
  }[];
  generated_files: GeneratedFile[];
  implementation?: { branch: string; changed_files: string[]; diff_summary: string; validation_status: string; validation_summary: string } | null;
  test_result?: { status: string; summary: string; passed: number; failed: number; executed_command: string } | null;
  pull_request?: { title: string; url: string; number: number; status?: string } | null;
  terminal_log: TerminalLogEntry[];
  mcp_audit: MCPAuditRecord[];
  audit_log: { timestamp: string; agent: string; action: string; status: string }[];
  llm_failover_history?: LLMFailoverEvent[];
  llm_keys_used?: string[];
  report?: WorkflowReport | null;
  created_at?: string;
  updated_at?: string;
};

export type LLMFailoverEvent = {
  timestamp: string;
  failed_key_id: string;
  failed_provider: string;
  reason: string;
  replacement_key_id?: string | null;
  replacement_provider?: string | null;
  resume_stage?: string | null;
};

export type WorkflowReport = {
  jira_key: string;
  summary: string;
  complexity_level: string;
  complexity_score: number;
  selected_model: string;
  validation_status: string;
  pr_url?: string | null;
  final_status: string;
  retry_count: number;
  duration_ms?: number | null;
  generated_at?: string | null;
  report_status?: "complete" | "partial";
  failure?: {
    stage?: string | null;
    stage_label?: string | null;
    error?: string | null;
    agent?: string | null;
  } | null;
  sections?: { id: string; label: string; status: string }[];
  requirement?: {
    jira_task?: Workflow["jira_task"];
    requirement_analysis?: {
      problem_summary: string;
      functional_requirement: string;
      acceptance_criteria: string[];
      constraints: string[];
      ambiguities: string[];
    } | null;
    scope_analysis?: Workflow["scope_analysis"];
    repository_analysis?: {
      project_type: string;
      relevant_directories: string[];
      relevant_files: string[];
      test_command?: string | null;
      notes: string;
    } | null;
    branch_analysis?: Workflow["branch_analysis"];
  } | null;
  planning?: {
    complexity?: Workflow["complexity"];
    model_recommendation?: Workflow["model_recommendation"];
    model_selection?: Workflow["model_selection"];
    selected_model?: string | null;
    plan?: {
      version: number;
      objective: string;
      affected_components: string[];
      likely_files: string[];
      implementation_steps: string[];
      test_approach: string[];
      risks: string[];
      expected_result: string;
      change_request?: string | null;
    } | null;
  } | null;
  build?: {
    base_branch?: string | null;
    work_branch?: string | null;
    branch_collision: boolean;
    collision_message?: string | null;
    changed_files: string[];
    diff_summary: string;
    files: { path: string; line_count: number }[];
  } | null;
  testing?: {
    validation_status: string;
    validation_summary: string;
    test_result?: Workflow["test_result"];
    terminal_log: TerminalLogEntry[];
  } | null;
  delivery?: {
    pull_request?: Workflow["pull_request"];
    pr_body?: string | null;
    jira_comment_posted: boolean;
    jira_transition_posted: boolean;
  } | null;
  audit_trail?: MCPAuditRecord[];
  llm_failover_history?: LLMFailoverEvent[];
  llm_keys_used?: string[];
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

export type LLMModelInfo = {
  provider: string;
  id: string;
  display_name?: string | null;
  owned_by?: string | null;
  active?: boolean;
};

export type LLMProviderModelsResponse = {
  provider: string;
  models: LLMModelInfo[];
};

export type LLMConfigurationSnapshot = {
  providers: Record<
    string,
    {
      configured_models: { default?: string; low?: string; medium?: string; high?: string };
      key_chain_ids: string[];
    }
  >;
  model_routing: Array<{
    complexity_min: number;
    complexity_max: number;
    provider: string;
    model: string;
    max_tokens: number;
  }>;
  llm_key_chain_order: string[];
};
