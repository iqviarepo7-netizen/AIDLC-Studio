import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import type { IssueLinkDirection, JiraIssueLinkTypeOption, PendingIssueLink } from "../../types/jiraCreate";
import { JiraSearchableSelect } from "./JiraSearchableSelect";

type Props = {
  projectId?: string;
  links: PendingIssueLink[];
  disabled?: boolean;
  onChange: (links: PendingIssueLink[]) => void;
};

type LinkChoice = {
  key: string;
  link_type_id: string;
  new_issue_role: IssueLinkDirection;
  label: string;
};

function linkChoicesFromTypes(linkTypes: JiraIssueLinkTypeOption[]): LinkChoice[] {
  return linkTypes.flatMap((type) => [
    {
      key: `${type.id}:outward`,
      link_type_id: type.id,
      new_issue_role: "outward",
      label: `This issue ${type.outward}`,
    },
    {
      key: `${type.id}:inward`,
      link_type_id: type.id,
      new_issue_role: "inward",
      label: `This issue ${type.inward}`,
    },
  ]);
}

export function JiraLinkedWorkItems({ projectId, links, disabled, onChange }: Props) {
  const [linkTypes, setLinkTypes] = useState<JiraIssueLinkTypeOption[]>([]);
  const [choiceKey, setChoiceKey] = useState("");
  const [targetKey, setTargetKey] = useState("");
  const [loadError, setLoadError] = useState<string>();

  const choices = useMemo(() => linkChoicesFromTypes(linkTypes), [linkTypes]);
  const selectedChoice = choices.find((item) => item.key === choiceKey);

  useEffect(() => {
    api
      .jiraCreateIssueLinkTypes()
      .then((response) => {
        setLinkTypes(response.link_types);
        const nextChoices = linkChoicesFromTypes(response.link_types);
        setChoiceKey(nextChoices[0]?.key ?? "");
      })
      .catch(() => setLoadError("Could not load Jira link types."));
  }, []);

  const addLink = () => {
    if (!selectedChoice) return;
    const key = targetKey.trim().toUpperCase();
    if (!key) return;
    const duplicate = links.some(
      (item) =>
        item.link_type_id === selectedChoice.link_type_id &&
        item.target_issue_key === key &&
        item.new_issue_role === selectedChoice.new_issue_role,
    );
    if (duplicate) return;
    onChange([
      ...links,
      {
        id: `${selectedChoice.key}-${key}-${Date.now()}`,
        link_type_id: selectedChoice.link_type_id,
        target_issue_key: key,
        new_issue_role: selectedChoice.new_issue_role,
      },
    ]);
    setTargetKey("");
  };

  const describeLink = (link: PendingIssueLink) => {
    const type = linkTypes.find((item) => item.id === link.link_type_id);
    if (!type) return link.target_issue_key;
    const verb = link.new_issue_role === "outward" ? type.outward : type.inward;
    return `This issue ${verb} ${link.target_issue_key}`;
  };

  return (
    <div className="jira-linked-work-items jira-field jira-compact" data-field-id="linked-work-items">
      <label htmlFor="jira-linked-relationship">Linked work items</label>
      <div className="jira-linked-work-items-controls">
        {loadError && <p className="muted">{loadError}</p>}
        <select
          id="jira-linked-relationship"
          className="jira-control"
          value={choiceKey}
          disabled={disabled || choices.length === 0}
          onChange={(event) => setChoiceKey(event.target.value)}
        >
          {choices.map((choice) => (
            <option key={choice.key} value={choice.key}>
              {choice.label}
            </option>
          ))}
        </select>
        <JiraSearchableSelect
          id="jira-linked-issue-target"
          value={targetKey}
          options={[]}
          placeholder="Select work item…"
          projectId={projectId}
          searchKind="issue"
          onChange={setTargetKey}
        />
        <button type="button" className="ghost small jira-linked-add" disabled={disabled || !selectedChoice || !targetKey} onClick={addLink}>
          Add
        </button>
        {links.length > 0 && (
          <ul className="jira-linked-work-items-list">
            {links.map((link) => (
              <li key={link.id}>
                <span>{describeLink(link)}</span>
                <button
                  type="button"
                  className="ghost small"
                  disabled={disabled}
                  onClick={() => onChange(links.filter((item) => item.id !== link.id))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
