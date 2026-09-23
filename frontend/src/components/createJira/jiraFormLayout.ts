import type { JiraCreateMetadata, ParsedJiraField } from "../../types/jiraCreate";

export const CONTEXT_MANAGED_FIELD_IDS = new Set([
  "project",
  "issuetype",
  "projectField",
  "issuetypeField",
  "parent",
]);

const PRIMARY_ORDER = ["summary", "description"];

export function visibleJiraTabs(metadata: JiraCreateMetadata) {
  return metadata.sorted_tabs.filter((tab) => tab.fields.length > 0);
}

export function orderFieldIds(fieldIds: string[], fields: Record<string, ParsedJiraField>): string[] {
  const unique = [...new Set(fieldIds)].filter((id) => !CONTEXT_MANAGED_FIELD_IDS.has(id) && fields[id]);
  const primary = PRIMARY_ORDER.filter((id) => unique.includes(id));
  const rest = unique.filter((id) => !PRIMARY_ORDER.includes(id));
  return [...primary, ...rest];
}

export function fieldsForRender(metadata: JiraCreateMetadata, activeTabFieldIds?: string[]): string[] {
  const tabs = visibleJiraTabs(metadata);
  if (tabs.length > 0 && activeTabFieldIds) {
    return orderFieldIds(activeTabFieldIds, metadata.fields);
  }
  return orderFieldIds(Object.keys(metadata.fields), metadata.fields);
}

export function splitPrimaryFields(metadata: JiraCreateMetadata, fieldIds: string[]) {
  const summary = fieldIds.includes("summary") ? metadata.fields.summary : undefined;
  const description = fieldIds.includes("description") ? metadata.fields.description : undefined;
  const secondary = fieldIds.filter((id) => id !== "summary" && id !== "description");
  return { summary, description, secondary };
}
