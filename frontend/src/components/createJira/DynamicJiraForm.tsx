import { useMemo, useState } from "react";
import type { JiraCreateMetadata, JiraFieldErrors, JiraFormValues } from "../../types/jiraCreate";
import { DynamicField } from "./DynamicField";
import { fieldsForRender, splitPrimaryFields, visibleJiraTabs } from "./jiraFormLayout";

type Props = {
  metadata?: JiraCreateMetadata;
  values: JiraFormValues;
  errors: JiraFieldErrors;
  loading: boolean;
  loadError?: string;
  creating: boolean;
  createAnother: boolean;
  onCreateAnotherChange: (checked: boolean) => void;
  onChange: (fieldId: string, value: unknown, userEdited?: boolean) => void;
  onCancel: () => void;
  onCreate: () => void;
  missingSummary?: string;
};

export function DynamicJiraForm({
  metadata,
  values,
  errors,
  loading,
  loadError,
  creating,
  createAnother,
  onCreateAnotherChange,
  onChange,
  onCancel,
  onCreate,
  missingSummary,
}: Props) {
  const tabs = useMemo(() => (metadata ? visibleJiraTabs(metadata) : []), [metadata]);
  const [activeTabId, setActiveTabId] = useState<string>("");

  const resolvedTabId = useMemo(() => {
    if (activeTabId && tabs.some((tab) => tab.id === activeTabId)) return activeTabId;
    return tabs[0]?.id ?? "";
  }, [activeTabId, tabs]);

  const activeTab = tabs.find((tab) => tab.id === resolvedTabId);
  const fieldIds = useMemo(() => {
    if (!metadata) return [];
    return fieldsForRender(metadata, activeTab?.fields);
  }, [metadata, activeTab?.fields]);

  const { summary, description, secondary } = useMemo(() => {
    if (!metadata) return { summary: undefined, description: undefined, secondary: [] as string[] };
    return splitPrimaryFields(metadata, fieldIds);
  }, [metadata, fieldIds]);

  if (loading) {
    return (
      <section className="create-jira-form">
        <div className="panel-title">Create Jira</div>
        <p className="muted">Loading Jira create form metadata…</p>
      </section>
    );
  }

  if (loadError) {
    return (
      <section className="create-jira-form">
        <div className="panel-title">Create Jira</div>
        <div className="banner error">{loadError}</div>
        <button type="button" className="ghost" onClick={onCancel}>
          Close
        </button>
      </section>
    );
  }

  if (!metadata) {
    return (
      <section className="create-jira-form">
        <div className="panel-title">Create Jira</div>
        <p className="muted">Select a project and issue type to load the Jira form.</p>
      </section>
    );
  }

  return (
    <section className="create-jira-form jira-create-surface" aria-label="Create Jira form">
      <div className="panel-title">Create Jira</div>

      {tabs.length > 0 && (
        <div className="jira-tab-bar" role="tablist" aria-label="Jira field tabs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={tab.id === resolvedTabId}
              className={tab.id === resolvedTabId ? "active" : undefined}
              onClick={() => setActiveTabId(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      <div className="jira-create-scroll" role="tabpanel">
        {summary && (
          <DynamicField
            field={summary}
            value={values[summary.id]}
            error={errors[summary.id]}
            variant="jira-primary"
            onChange={(id, value) => onChange(id, value, true)}
          />
        )}
        {description && (
          <DynamicField
            field={description}
            value={values[description.id]}
            error={errors[description.id]}
            variant="jira-description"
            onChange={(id, value) => onChange(id, value, true)}
          />
        )}
        <div className="jira-create-field-list">
          {secondary.map((fieldId) => {
            const field = metadata.fields[fieldId];
            if (!field) return null;
            return (
              <DynamicField
                key={field.id}
                field={field}
                value={values[field.id]}
                error={errors[field.id]}
                variant="jira-compact"
                onChange={(id, value) => onChange(id, value, true)}
              />
            );
          })}
        </div>
      </div>

      {missingSummary && <p className="warning-text jira-create-missing">{missingSummary}</p>}

      <div className="create-jira-footer">
        <label className="option-item create-another">
          <input type="checkbox" checked={createAnother} onChange={(event) => onCreateAnotherChange(event.target.checked)} />
          Create another
        </label>
        <div className="create-jira-actions">
          <button type="button" className="ghost" onClick={onCancel} disabled={creating}>
            Cancel
          </button>
          <button type="button" onClick={onCreate} disabled={creating || Boolean(loadError) || Object.keys(errors).length > 0}>
            {creating ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </section>
  );
}
