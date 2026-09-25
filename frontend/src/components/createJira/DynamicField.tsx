import type { JiraCreateMetadata, JiraFieldErrors, JiraFormValues, ParsedJiraField } from "../../types/jiraCreate";
import { ColorPickerField } from "./ColorPickerField";
import { displayFieldLabel } from "./jiraFormLayout";
import { JiraSelectField } from "./JiraSelectField";

type Props = {
  field: ParsedJiraField;
  value: unknown;
  error?: string;
  projectId?: string;
  issueTypeId?: string;
  variant?: "default" | "jira-compact";
  layoutModifiers?: string[];
  onChange: (fieldId: string, value: unknown) => void;
};

export function DynamicField({
  field,
  value,
  error,
  projectId,
  issueTypeId,
  variant = "default",
  layoutModifiers = [],
  onChange,
}: Props) {
  const inputId = `jira-field-${field.id}`;
  const describedBy = field.description ? `${inputId}-desc` : undefined;
  const isOptionField = field.type === "checkbox" || field.type === "radio";

  const rootClass = [
    "jira-field",
    variant !== "default" ? variant : "",
    ...layoutModifiers,
    field.type === "unsupported" ? "unsupported" : "",
    isOptionField && variant === "jira-compact" ? "jira-field-options" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const label = displayFieldLabel(field);
  const placeholder =
    field.id === "summary" ? "Summary" : field.id === "description" ? "Add a description…" : undefined;
  const showError = Boolean(error && !String(error).endsWith(" is required."));

  if (field.type === "readonly") {
    const display =
      value !== undefined && value !== null && String(value).trim()
        ? String(value)
        : field.default_value !== undefined && field.default_value !== null
          ? String(field.default_value)
          : "—";
    return (
      <div className={rootClass} data-field-id={field.id}>
        <label htmlFor={inputId}>
          {label}
          {field.required && <span className="required-mark">*</span>}
        </label>
        <p className="jira-readonly-value" id={inputId}>
          {display}
        </p>
      </div>
    );
  }

  if (field.type === "unsupported") {
    return (
      <div className={rootClass} data-field-id={field.id}>
        <label htmlFor={inputId}>
          {label}
          {field.required && <span className="required-mark">*</span>}
        </label>
        <p className="muted" id={inputId}>
          This field type is not supported in AIDLC Studio. Set it in Jira after creation if needed.
        </p>
        {field.description && (
          <p className="field-description" id={`${inputId}-desc`}>
            {field.description}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={rootClass} data-field-id={field.id}>
      {isOptionField ? (
        <span className="jira-field-label" id={`${inputId}-legend`}>
          {label}
          {field.required && <span className="required-mark">*</span>}
        </span>
      ) : (
        <label htmlFor={inputId}>
          {label}
          {field.required && <span className="required-mark">*</span>}
        </label>
      )}
      {field.description && variant === "default" && (
        <p className="field-description" id={`${inputId}-desc`}>
          {field.description}
        </p>
      )}
      {renderControl(field, value, inputId, describedBy, onChange, placeholder, variant, projectId, issueTypeId)}
      {showError && <p className="field-error" role="alert">{error}</p>}
    </div>
  );
}

function renderControl(
  field: ParsedJiraField,
  value: unknown,
  inputId: string,
  describedBy: string | undefined,
  onChange: (fieldId: string, value: unknown) => void,
  placeholder?: string,
  variant: Props["variant"] = "default",
  projectId?: string,
  issueTypeId?: string,
) {
  const compact = variant === "jira-compact";
  const stringValue = typeof value === "string" ? value : "";

  switch (field.type) {
    case "textarea":
      return (
        <textarea
          id={inputId}
          className="jira-control"
          aria-describedby={describedBy}
          aria-label={compact ? field.label : undefined}
          placeholder={placeholder ?? (compact ? field.label : undefined)}
          required={field.required}
          value={stringValue}
          onChange={(event) => onChange(field.id, event.target.value)}
          rows={field.id === "description" ? 4 : compact ? 2 : 6}
        />
      );
    case "color-picker":
      return (
        <ColorPickerField
          id={inputId}
          describedBy={describedBy}
          required={field.required}
          value={stringValue}
          options={field.options}
          onChange={(next) => onChange(field.id, next)}
        />
      );
    case "status":
    case "priority":
    case "select":
      return (
        <JiraSelectField
          id={inputId}
          describedBy={describedBy}
          required={field.required}
          value={stringValue}
          placeholder="Select…"
          options={field.options}
          onChange={(next) => onChange(field.id, next)}
        />
      );
    case "parent":
      return (
        <JiraSelectField
          id={inputId}
          describedBy={describedBy}
          required={field.required}
          value={stringValue}
          placeholder="Select parent…"
          options={field.options}
          searchable={field.searchable}
          searchKind="parent"
          projectId={projectId}
          issueTypeId={issueTypeId}
          onChange={(next) => onChange(field.id, next)}
        />
      );
    case "user":
      return (
        <JiraSelectField
          id={inputId}
          describedBy={describedBy}
          required={field.required}
          value={stringValue}
          placeholder="Automatic"
          options={field.options}
          searchable={field.searchable}
          searchKind="user"
          projectId={projectId}
          onChange={(next) => onChange(field.id, next)}
        />
      );
    case "number":
      return (
        <input
          id={inputId}
          className="jira-control"
          type="number"
          step="any"
          aria-describedby={describedBy}
          aria-label={compact ? field.label : undefined}
          required={field.required}
          value={stringValue}
          onChange={(event) => onChange(field.id, event.target.value)}
        />
      );
    case "labels":
      return (
        <input
          id={inputId}
          className="jira-control"
          type="text"
          aria-describedby={describedBy}
          aria-label={compact ? field.label : undefined}
          placeholder={compact ? "Add labels…" : "Comma-separated labels"}
          required={field.required}
          value={Array.isArray(value) ? value.join(", ") : typeof value === "string" ? value : ""}
          onChange={(event) => {
            const parts = event.target.value
              .split(",")
              .map((part) => part.trim())
              .filter(Boolean);
            onChange(field.id, parts);
          }}
        />
      );
    case "date":
      return (
        <input
          id={inputId}
          className="jira-control"
          type="date"
          aria-describedby={describedBy}
          required={field.required}
          value={stringValue}
          onChange={(event) => onChange(field.id, event.target.value)}
        />
      );
    case "datetime":
      return (
        <input
          id={inputId}
          className="jira-control"
          type="datetime-local"
          aria-describedby={describedBy}
          required={field.required}
          value={stringValue}
          onChange={(event) => onChange(field.id, event.target.value)}
        />
      );
    case "radio":
      return (
        <div className="option-group jira-option-group" role="radiogroup" aria-labelledby={`${inputId}-legend`}>
          {field.options.map((option) => (
            <label key={option.value} className="option-item jira-option-item">
              <input
                type="radio"
                name={field.id}
                value={option.value}
                checked={String(value) === option.value}
                disabled={option.disabled}
                onChange={() => onChange(field.id, option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      );
    case "checkbox":
      return (
        <div className="option-group jira-option-group" role="group" aria-labelledby={`${inputId}-legend`}>
          {field.options.map((option) => {
            const selected = Array.isArray(value) ? value.map(String).includes(option.value) : String(value) === option.value;
            return (
              <label key={option.value} className="option-item jira-option-item">
                <input
                  type="checkbox"
                  value={option.value}
                  checked={selected}
                  disabled={option.disabled}
                  onChange={(event) => {
                    const current = Array.isArray(value) ? value.map(String) : value ? [String(value)] : [];
                    if (event.target.checked) onChange(field.id, [...new Set([...current, option.value])]);
                    else onChange(field.id, current.filter((item) => item !== option.value));
                  }}
                />
                <span>{option.label}</span>
              </label>
            );
          })}
        </div>
      );
    default:
      return (
        <input
          id={inputId}
          className="jira-control"
          type="text"
          aria-describedby={describedBy}
          aria-label={compact ? field.label : undefined}
          placeholder={placeholder ?? (compact ? field.label : undefined)}
          required={field.required}
          value={stringValue}
          onChange={(event) => onChange(field.id, event.target.value)}
        />
      );
  }
}

const CONTEXT_MANAGED_FIELD_IDS = new Set(["project", "issuetype", "projectField", "issuetypeField"]);

export function isFieldEmpty(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "string") return !value.trim();
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

function isEffectivelyRequired(metadata: { fields: Record<string, ParsedJiraField>; required_field_ids?: string[] }, fieldId: string): boolean {
  if (metadata.required_field_ids && metadata.required_field_ids.length > 0) {
    return metadata.required_field_ids.includes(fieldId);
  }
  return Boolean(metadata.fields[fieldId]?.required);
}

export function normalizeSubmitValues(values: JiraFormValues): JiraFormValues {
  const next = { ...values };
  if (typeof next.summary === "string") {
    next.summary = next.summary.trim();
  }
  return next;
}

export function computeFieldErrors(metadata: JiraCreateMetadata, values: JiraFormValues): JiraFieldErrors {
  const errors: JiraFieldErrors = {};
  const normalized = normalizeSubmitValues(values);
  Object.values(metadata.fields).forEach((field) => {
    if (CONTEXT_MANAGED_FIELD_IDS.has(field.id)) return;
    const current = field.id === "summary" ? normalized[field.id] : values[field.id];
    if (isEffectivelyRequired(metadata, field.id) && isFieldEmpty(current)) {
      errors[field.id] = `${field.label} is required.`;
    }
    if (field.type === "number" && !isFieldEmpty(values[field.id])) {
      const raw = String(values[field.id]).trim();
      if (Number.isNaN(Number(raw))) {
        errors[field.id] = `${field.label} must be a valid number.`;
      }
    }
    if (
      field.type === "select" ||
      field.type === "radio" ||
      field.type === "status" ||
      field.type === "priority" ||
      field.type === "color-picker"
    ) {
      const current = values[field.id];
      if (!isFieldEmpty(current) && field.options.length > 0) {
        const allowed = new Set(field.options.map((option) => option.value));
        const currentText = String(current);
        const sprintLike = field.label.toLowerCase().includes("sprint");
        if (!allowed.has(currentText) && !(sprintLike && /^\d+$/.test(currentText))) {
          errors[field.id] = `${field.label} must use a valid Jira option.`;
        }
      }
    }
    if (field.type === "parent" && !field.searchable) {
      const current = values[field.id];
      if (!isFieldEmpty(current) && field.options.length > 0) {
        const allowed = new Set(field.options.map((option) => option.value));
        if (!allowed.has(String(current))) {
          errors[field.id] = `${field.label} must use a valid Jira option.`;
        }
      }
    }
    if (field.type === "parent" && field.searchable && !isFieldEmpty(values[field.id])) {
      const key = String(values[field.id]).trim();
      const expectsIssueId = field.id.toLowerCase() === "parentid" || field.id.toLowerCase().endsWith("parentid");
      if (expectsIssueId) {
        if (!/^\d+$/.test(key)) {
          errors[field.id] = `${field.label} must be a valid Jira issue id.`;
        }
      } else if (!key.includes("-")) {
        errors[field.id] = `${field.label} must be a valid Jira issue key.`;
      }
    }
    if (field.type === "user" && !field.searchable) {
      const current = values[field.id];
      if (!isFieldEmpty(current) && field.options.length > 0) {
        const allowed = new Set(field.options.map((option) => option.value));
        if (!allowed.has(String(current))) {
          errors[field.id] = `${field.label} must use a valid Jira option.`;
        }
      }
    }
  });
  return errors;
}
