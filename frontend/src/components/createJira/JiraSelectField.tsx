import type { JiraFieldOption } from "../../types/jiraCreate";
import { JiraSearchableSelect } from "./JiraSearchableSelect";

type Props = {
  id: string;
  value: string;
  options: JiraFieldOption[];
  placeholder?: string;
  required?: boolean;
  describedBy?: string;
  searchable?: boolean;
  searchKind?: "user" | "issue" | "parent";
  projectId?: string;
  issueTypeId?: string;
  onChange: (value: string) => void;
};

/** Native `<select>` using the same Create Jira / AIDLC form select styling as project & issue type pickers. */
export function JiraSelectField({
  id,
  value,
  options,
  placeholder = "Select…",
  required,
  describedBy,
  searchable,
  searchKind = "user",
  projectId,
  issueTypeId,
  onChange,
}: Props) {
  if (searchable) {
    return (
      <JiraSearchableSelect
        id={id}
        value={value}
        options={options}
        placeholder={placeholder}
        required={required}
        describedBy={describedBy}
        projectId={projectId}
        issueTypeId={issueTypeId}
        searchKind={searchKind}
        onChange={onChange}
      />
    );
  }

  return (
    <div className="jira-select-field">
      <select
        id={id}
        className="jira-control"
        aria-describedby={describedBy}
        required={required}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.value || `opt-${option.label}`} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
