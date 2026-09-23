export type JiraFieldOption = {
  label: string;
  value: string;
  disabled?: boolean;
  selected?: boolean;
};

export type ParsedJiraField = {
  id: string;
  label: string;
  required: boolean;
  type: "text" | "textarea" | "select" | "checkbox" | "radio" | "unsupported";
  options: JiraFieldOption[];
  description?: string | null;
  tab?: string | null;
  default_value?: unknown;
};

export type JiraTabDefinition = {
  id: string;
  label: string;
  position: number;
  fields: string[];
};

export type JiraCreateMetadata = {
  project_id: string;
  issue_type_id: string;
  project_key?: string | null;
  issue_type_name?: string | null;
  fields: Record<string, ParsedJiraField>;
  sorted_tabs: JiraTabDefinition[];
};

export type JiraProjectOption = {
  id: string;
  key: string;
  name: string;
};

export type JiraIssueTypeOption = {
  id: string;
  name: string;
  description?: string | null;
};

export type JiraFormValues = Record<string, unknown>;

export type JiraFieldErrors = Record<string, string>;

export type AgentMessage = {
  role: "user" | "assistant";
  content: string;
};

export type MissingRequiredField = {
  id: string;
  label: string;
  question: string;
};

export type CreateJiraAgentResponse = {
  status: "needs_information" | "ready";
  message: string;
  fields: JiraFormValues;
  missing_required_fields: MissingRequiredField[];
};

export type CreateJiraIssueResponse = {
  key: string;
  id?: string | null;
  self_url?: string | null;
};
