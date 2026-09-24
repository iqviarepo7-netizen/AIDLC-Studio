import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api";
import type {
  AgentMessage,
  CreateJiraIssueLinkRequest,
  JiraCreatedNotice,
  JiraCreateMetadata,
  JiraFormValues,
  JiraIssueTypeOption,
  JiraProjectOption,
  PendingIssueLink,
  PendingJiraAttachment,
} from "../../types/jiraCreate";
import { computeFieldErrors, normalizeSubmitValues } from "./DynamicField";
import { CreateJiraAgentPanel } from "./CreateJiraAgentPanel";
import { DynamicJiraForm } from "./DynamicJiraForm";

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (jiraKey: string, notice?: JiraCreatedNotice) => void;
};

export function CreateJiraModal({ open, onClose, onCreated }: Props) {
  const [projects, setProjects] = useState<JiraProjectOption[]>([]);
  const [issueTypes, setIssueTypes] = useState<JiraIssueTypeOption[]>([]);
  const [projectId, setProjectId] = useState("");
  const [issueTypeId, setIssueTypeId] = useState("");
  const [metadata, setMetadata] = useState<JiraCreateMetadata>();
  const [values, setValues] = useState<JiraFormValues>({});
  const [userEdited, setUserEdited] = useState<Set<string>>(() => new Set());
  const [attachments, setAttachments] = useState<PendingJiraAttachment[]>([]);
  const [issueLinks, setIssueLinks] = useState<PendingIssueLink[]>([]);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [pendingClarificationFieldId, setPendingClarificationFieldId] = useState<string | null>(null);
  const [conversationPhase, setConversationPhase] = useState<
    "initial_requirement" | "field_resolution" | "ready_to_create" | null
  >(null);
  const [pendingFields, setPendingFields] = useState<import("../../types/jiraCreate").PendingAgentField[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingIssueTypes, setLoadingIssueTypes] = useState(false);
  const [loadingMetadata, setLoadingMetadata] = useState(false);
  const [agentBusy, setAgentBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string>();

  const issueTypesRequestRef = useRef(0);
  const metadataRequestRef = useRef(0);
  const createInFlightRef = useRef(false);

  const resetIssueState = useCallback(() => {
    setValues({});
    setUserEdited(new Set());
    setMessages([]);
    setPendingClarificationFieldId(null);
    setConversationPhase(null);
    setPendingFields([]);
    setMetadata(undefined);
    setIssueTypeId("");
    setAttachments([]);
    setIssueLinks([]);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setError(undefined);
    setLoadingProjects(true);
    api
      .jiraCreateProjects()
      .then((response) => {
        const loaded = response.projects;
        setProjects(loaded);
        if (loaded.length === 1) {
          setProjectId(loaded[0].id);
        } else {
          setProjectId("");
          setIssueTypes([]);
          setIssueTypeId("");
          setMetadata(undefined);
        }
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load Jira projects."))
      .finally(() => setLoadingProjects(false));
  }, [open]);

  useEffect(() => {
    if (!open || !projectId) {
      setIssueTypes([]);
      setLoadingIssueTypes(false);
      return;
    }
    const requestId = ++issueTypesRequestRef.current;
    setLoadingIssueTypes(true);
    setIssueTypeId("");
    setError(undefined);
    api
      .jiraCreateIssueTypes(projectId)
      .then((response) => {
        if (requestId !== issueTypesRequestRef.current) return;
        setIssueTypes(response.issue_types);
      })
      .catch((cause) => {
        if (requestId !== issueTypesRequestRef.current) return;
        setIssueTypes([]);
        setIssueTypeId("");
        setError(cause instanceof Error ? cause.message : "Could not load issue types.");
      })
      .finally(() => {
        if (requestId === issueTypesRequestRef.current) setLoadingIssueTypes(false);
      });
  }, [open, projectId]);

  useEffect(() => {
    if (!open || !projectId || !issueTypeId) {
      setMetadata(undefined);
      return;
    }
    const requestId = ++metadataRequestRef.current;
    setLoadingMetadata(true);
    setError(undefined);
    api
      .jiraCreateMetadata(projectId, issueTypeId)
      .then((response) => {
        if (requestId !== metadataRequestRef.current) return;
        setMetadata(response);
        setValues((current) =>
          applyMetadataDefaults(sanitizeParentValues(pruneValues(current, response), response), response),
        );
        setAttachments([]);
        setIssueLinks([]);
      })
      .catch((cause) => {
        if (requestId !== metadataRequestRef.current) return;
        setMetadata(undefined);
        setError(cause instanceof Error ? cause.message : "Could not load Jira create metadata.");
      })
      .finally(() => {
        if (requestId === metadataRequestRef.current) setLoadingMetadata(false);
      });
  }, [open, projectId, issueTypeId]);

  const fieldErrors = useMemo(() => (metadata ? computeFieldErrors(metadata, values) : {}), [metadata, values]);

  const projectLabel = projects.find((item) => item.id === projectId);
  const issueTypeLabel = issueTypes.find((item) => item.id === issueTypeId);
  const agentReady = Boolean(projectId && issueTypeId && metadata && !loadingMetadata);

  const handleFieldChange = (fieldId: string, value: unknown, userEditedField = false) => {
    setValues((current) => ({ ...current, [fieldId]: value }));
    if (userEditedField) {
      setUserEdited((current) => new Set(current).add(fieldId));
    }
  };

  const handleAgentSend = async (content: string) => {
    if (!projectId || !issueTypeId) {
      setError("Select a project and issue type before chatting with the agent.");
      return;
    }
    const nextMessages: AgentMessage[] = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setAgentBusy(true);
    setError(undefined);
    try {
      const response = await api.jiraCreateAgent({
        messages: nextMessages,
        project_id: projectId,
        issue_type_id: issueTypeId,
        project_label: projectLabel ? `${projectLabel.name} (${projectLabel.key})` : undefined,
        issue_type_label: issueTypeLabel?.name,
        current_values: values,
        user_edited_field_ids: [...userEdited],
        pending_clarification_field_id: pendingClarificationFieldId ?? undefined,
        conversation_phase: conversationPhase ?? undefined,
        pending_fields: pendingFields,
      });
      setMessages([...nextMessages, { role: "assistant", content: response.message }]);
      setValues((current) => ({ ...current, ...response.fields }));
      setPendingClarificationFieldId(response.pending_clarification_field_id ?? null);
      setConversationPhase(response.conversation_phase ?? null);
      setPendingFields(response.pending_fields ?? []);
      if (response.issue_links && response.issue_links.length > 0) {
        setIssueLinks((current) => mergeAgentIssueLinks(current, response.issue_links ?? []));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Create Jira Agent failed.");
    } finally {
      setAgentBusy(false);
    }
  };

  const handleCreate = async () => {
    if (!metadata || !projectId || !issueTypeId) return;
    if (Object.keys(fieldErrors).length > 0) return;
    if (createInFlightRef.current) return;
    createInFlightRef.current = true;
    setCreating(true);
    setError(undefined);
    const fields = normalizeSubmitValues(values);
    try {
      const result = await api.jiraCreateIssue({
        project_id: projectId,
        issue_type_id: issueTypeId,
        fields,
        issue_links: issueLinks.map((link) => ({
          link_type_id: link.link_type_id,
          target_issue_key: link.target_issue_key,
          new_issue_role: link.new_issue_role,
        })),
      });
      let partial = Boolean(result.partial_success);
      let message = result.message ?? `Jira ${result.key} created successfully.`;
      const postOps = [...(result.post_create_operations ?? [])];

      if (attachments.length > 0) {
        const attachmentResult = await api.jiraCreateIssueAttachments(
          result.key,
          attachments.map((item) => item.file),
        );
        if (attachmentResult.partial_success) {
          partial = true;
          message = attachmentResult.message ?? message;
        }
        postOps.push(...(attachmentResult.post_create_operations ?? []));
      }

      if (partial) {
        message =
          message ||
          `Jira ${result.key} was created successfully, but some additional operations could not be completed.`;
      }

      const successNotice: JiraCreatedNotice = {
        partial,
        detail: partial
          ? message || "Some additional operations could not be completed."
          : undefined,
        browseUrl: result.browse_url ?? null,
      };
      onCreated(result.key, successNotice);
      if (partial) {
        const details = postOps
          .filter((item) => !item.success)
          .map((item) => item.detail || item.operation)
          .join("; ");
        setError(details ? `${message} ${details}` : message);
      } else {
        onClose();
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Jira creation failed.");
    } finally {
      createInFlightRef.current = false;
      setCreating(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <div
      className="create-jira-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-jira-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="create-jira-modal jira-create-surface">
        <div className="create-jira-head">
          <h2 id="create-jira-title">Create Jira Agent</h2>
          <button type="button" className="ghost small" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="create-jira-selectors">
          <label>
            Project
            <div className="jira-select-field">
              <select
                className="jira-control"
                value={projectId}
                disabled={loadingProjects}
                onChange={(event) => {
                  setProjectId(event.target.value);
                  resetIssueState();
                }}
              >
                <option value="">Select project…</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name} ({project.key})
                  </option>
                ))}
              </select>
            </div>
          </label>
          <label>
            Issue type
            <div className="jira-select-field">
              <select
                className="jira-control"
                value={issueTypeId}
                disabled={!projectId || loadingIssueTypes}
                onChange={(event) => {
                  setIssueTypeId(event.target.value);
                  setValues({});
                  setUserEdited(new Set());
                  setMessages([]);
                  setAttachments([]);
                  setIssueLinks([]);
                }}
              >
                <option value="">{loadingIssueTypes ? "Loading issue types…" : "Select issue type…"}</option>
                {issueTypes.map((issueType) => (
                  <option key={issueType.id} value={issueType.id}>
                    {issueType.name}
                  </option>
                ))}
              </select>
            </div>
          </label>
        </div>

        {error && <div className="banner error">{error}</div>}

        <div className="create-jira-panels">
          <CreateJiraAgentPanel messages={messages} busy={agentBusy} ready={agentReady} onSend={handleAgentSend} />
          <DynamicJiraForm
            projectId={projectId}
            metadata={metadata}
            values={values}
            errors={fieldErrors}
            loading={loadingMetadata}
            loadError={!loadingMetadata && projectId && issueTypeId && !metadata ? error : undefined}
            creating={creating}
            attachments={attachments}
            onAttachmentsChange={setAttachments}
            issueLinks={issueLinks}
            onIssueLinksChange={setIssueLinks}
            onChange={handleFieldChange}
            onCancel={onClose}
            onCreate={handleCreate}
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}

function sanitizeParentValues(values: JiraFormValues, metadata: JiraCreateMetadata): JiraFormValues {
  const next = { ...values };
  Object.values(metadata.fields).forEach((field) => {
    if (field.type !== "parent") return;
    const current = next[field.id];
    if (current === undefined || current === "") return;
    if (field.options.length === 0) return;
    const allowed = new Set(field.options.map((option) => option.value));
    if (!allowed.has(String(current))) {
      delete next[field.id];
      if (field.id === "parent") {
        delete next.parentId;
      }
      if (field.id.toLowerCase().endsWith("parentid")) {
        delete next.parent;
      }
    }
  });
  return next;
}

function pruneValues(values: JiraFormValues, metadata: JiraCreateMetadata): JiraFormValues {
  const allowed = new Set(Object.keys(metadata.fields));
  const next: JiraFormValues = {};
  Object.entries(values).forEach(([key, value]) => {
    if (allowed.has(key)) next[key] = value;
  });
  return next;
}

function applyMetadataDefaults(values: JiraFormValues, metadata: JiraCreateMetadata): JiraFormValues {
  const next = { ...values };
  Object.values(metadata.fields).forEach((field) => {
    if (next[field.id] !== undefined && next[field.id] !== "") return;
    if (field.default_value !== undefined && field.default_value !== null && field.default_value !== "") {
      next[field.id] = field.default_value;
    }
  });
  return next;
}

function mergeAgentIssueLinks(current: PendingIssueLink[], incoming: CreateJiraIssueLinkRequest[]): PendingIssueLink[] {
  const next = [...current];
  incoming.forEach((link, index) => {
    const duplicate = next.some(
      (item) =>
        item.link_type_id === link.link_type_id &&
        item.target_issue_key === link.target_issue_key &&
        item.new_issue_role === link.new_issue_role,
    );
    if (duplicate) return;
    next.push({
      id: `agent-${link.link_type_id}-${link.new_issue_role}-${link.target_issue_key}-${Date.now()}-${index}`,
      link_type_id: link.link_type_id,
      target_issue_key: link.target_issue_key,
      new_issue_role: link.new_issue_role,
    });
  });
  return next;
}
