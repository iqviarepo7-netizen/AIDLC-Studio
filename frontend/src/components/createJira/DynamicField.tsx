import type { JiraFieldErrors, JiraFormValues, ParsedJiraField } from "../../types/jiraCreate";

type Props = {
  field: ParsedJiraField;
  value: unknown;
  error?: string;
  variant?: "default" | "jira-primary" | "jira-description" | "jira-compact";
  onChange: (fieldId: string, value: unknown) => void;
};

export function DynamicField({ field, value, error, variant = "default", onChange }: Props) {
  const inputId = `jira-field-${field.id}`;
  const describedBy = field.description ? `${inputId}-desc` : undefined;

  const rootClass = ["jira-field", variant !== "default" ? variant : "", field.type === "unsupported" ? "unsupported" : ""]
    .filter(Boolean)
    .join(" ");

  if (field.type === "unsupported") {
    return (
      <div className={rootClass} data-field-id={field.id}>
        <label htmlFor={inputId}>
          {field.label}
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

  const hideLabel = variant === "jira-primary" || variant === "jira-description";
  const placeholder =
    variant === "jira-primary" ? "Summary" : variant === "jira-description" ? "Add a description…" : undefined;

  return (
    <div className={rootClass} data-field-id={field.id}>
      {!hideLabel && (
        <label htmlFor={inputId}>
          {field.label}
          {field.required && <span className="required-mark">*</span>}
        </label>
      )}
      {field.description && variant === "default" && (
        <p className="field-description" id={`${inputId}-desc`}>
          {field.description}
        </p>
      )}
      {renderControl(field, value, inputId, describedBy, onChange, placeholder, variant)}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
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
) {
  const compact = variant === "jira-compact";
  switch (field.type) {
    case "textarea":
      return (
        <textarea
          id={inputId}
          aria-describedby={describedBy}
          aria-label={compact ? field.label : undefined}
          placeholder={placeholder ?? (compact ? field.label : undefined)}
          required={field.required}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(field.id, event.target.value)}
          rows={variant === "jira-description" ? 4 : compact ? 2 : 6}
        />
      );
    case "select":
      return (
        <select
          id={inputId}
          aria-describedby={describedBy}
          required={field.required}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(field.id, event.target.value)}
        >
          <option value="">Select…</option>
          {field.options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
      );
    case "radio":
      return (
        <div className="option-group" role="radiogroup" aria-labelledby={`${inputId}-legend`}>
          <span id={`${inputId}-legend`} className="sr-only">
            {field.label}
          </span>
          {field.options.map((option) => (
            <label key={option.value} className="option-item">
              <input
                type="radio"
                name={field.id}
                value={option.value}
                checked={String(value) === option.value}
                disabled={option.disabled}
                onChange={() => onChange(field.id, option.value)}
              />
              {option.label}
            </label>
          ))}
        </div>
      );
    case "checkbox":
      return (
        <div className="option-group" role="group" aria-labelledby={`${inputId}-legend`}>
          <span id={`${inputId}-legend`} className="sr-only">
            {field.label}
          </span>
          {field.options.map((option) => {
            const selected = Array.isArray(value) ? value.map(String).includes(option.value) : String(value) === option.value;
            return (
              <label key={option.value} className="option-item">
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
                {option.label}
              </label>
            );
          })}
        </div>
      );
    default:
      return (
        <input
          id={inputId}
          type="text"
          aria-describedby={describedBy}
          aria-label={compact ? field.label : undefined}
          placeholder={placeholder ?? (compact ? field.label : undefined)}
          required={field.required}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(field.id, event.target.value)}
        />
      );
  }
}

const CONTEXT_MANAGED_FIELD_IDS = new Set(["project", "issuetype", "projectField", "issuetypeField", "parent"]);

export function isFieldEmpty(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "string") return !value.trim();
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

export function computeFieldErrors(metadata: { fields: Record<string, ParsedJiraField> }, values: JiraFormValues): JiraFieldErrors {
  const errors: JiraFieldErrors = {};
  Object.values(metadata.fields).forEach((field) => {
    if (CONTEXT_MANAGED_FIELD_IDS.has(field.id)) return;
    if (field.required && isFieldEmpty(values[field.id])) {
      errors[field.id] = `${field.label} is required.`;
    }
    if (field.type === "select" || field.type === "radio") {
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
