export type JiraFieldOption = {
  label: string;
  value: string;
  disabled?: boolean;
  selected?: boolean;
  swatch_color?: string | null;
};

export type ParsedJiraField = {
  id: string;
  label: string;
  required: boolean;
  type:
    | "text"
    | "textarea"
    | "number"
    | "select"
    | "checkbox"
    | "radio"
    | "labels"
    | "date"
    | "datetime"
    | "user"
    | "status"
    | "priority"
    | "parent"
    | "color-picker"
    | "readonly"
    | "unsupported";
  options: JiraFieldOption[];
  searchable?: boolean;
  multiple?: boolean;
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

export type JiraAttachmentConfig = {
  enabled: boolean;
  max_size_bytes?: number | null;
};

export type JiraCreateMetadata = {
  project_id: string;
  issue_type_id: string;
  project_key?: string | null;
  issue_type_name?: string | null;
  fields: Record<string, ParsedJiraField>;
  sorted_tabs: JiraTabDefinition[];
  required_field_ids?: string[];
  field_order?: string[];
  attachment_config?: JiraAttachmentConfig;
};

export type PendingJiraAttachment = {
  id: string;
  file: File;
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

export type PendingAgentField = {
  field_id: string;
  requested_value?: string | null;
};

export type IssueLinkDirection = "outward" | "inward";

export type CreateJiraIssueLinkRequest = {
  link_type_id: string;
  target_issue_key: string;
  new_issue_role: IssueLinkDirection;
};

export type CreateJiraAgentResponse = {
  status: "needs_information" | "ready";
  message: string;
  fields: JiraFormValues;
  missing_required_fields: MissingRequiredField[];
  pending_clarification_field_id?: string | null;
  conversation_phase?: "initial_requirement" | "field_resolution" | "ready_to_create";
  pending_fields?: PendingAgentField[];
  issue_links?: CreateJiraIssueLinkRequest[];
};

export type PostCreateOperationResult = {
  operation: string;
  success: boolean;
  detail?: string | null;
};

export type PendingIssueLink = {
  id: string;
  link_type_id: string;
  target_issue_key: string;
  new_issue_role: IssueLinkDirection;
};

export type JiraIssueLinkTypeOption = {
  id: string;
  name: string;
  inward: string;
  outward: string;
};

export type CreateJiraIssueResponse = {
  key: string;
  id?: string | null;
  self_url?: string | null;
  browse_url?: string | null;
  partial_success?: boolean;
  message?: string | null;
  post_create_operations?: PostCreateOperationResult[];
};

export type JiraCreatedNotice = {
  partial?: boolean;
  detail?: string;
  browseUrl?: string | null;
};

export type CreateJiraAttachmentResponse = {
  ok: boolean;
  count: number;
  partial_success?: boolean;
  message?: string | null;
  post_create_operations?: PostCreateOperationResult[];
};
