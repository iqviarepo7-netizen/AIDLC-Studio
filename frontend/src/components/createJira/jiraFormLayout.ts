import type { JiraCreateMetadata, ParsedJiraField } from "../../types/jiraCreate";

export const CONTEXT_MANAGED_FIELD_IDS = new Set(["project", "issuetype", "projectField", "issuetypeField"]);

/** Visible Create Jira slots in display order (not Jira field IDs). */
const CREATE_UI_SLOT_ORDER = [
  "summary",
  "description",
  "assignee",
  "duedate",
  "labels",
  "parent",
  "priority",
  "reporter",
  "sprint",
  "startdate",
  "storypoint",
  "development",
] as const;

type CreateUiSlot = (typeof CREATE_UI_SLOT_ORDER)[number];

function normalizeLabel(label: string): string {
  return label.trim().toLowerCase();
}

export function resolveCreateUiSlot(field: ParsedJiraField): CreateUiSlot | null {
  const id = field.id.toLowerCase();
  if (id === "summary") return "summary";
  if (id === "description") return "description";
  if (id === "assignee") return "assignee";
  if (id === "duedate") return "duedate";
  if (id === "labels") return "labels";
  if (id === "parent") return "parent";
  if (id === "priority") return "priority";
  if (id === "reporter") return "reporter";

  const label = normalizeLabel(field.label);
  if (label === "sprint" || label.startsWith("sprint ")) return "sprint";
  if (label.includes("start date") || label === "start") return "startdate";
  if (label.includes("story point")) return "storypoint";
  if (label === "development" || label.startsWith("development ")) return "development";

  return null;
}

function isEffectivelyRequired(metadata: JiraCreateMetadata, fieldId: string): boolean {
  if (metadata.required_field_ids && metadata.required_field_ids.length > 0) {
    return metadata.required_field_ids.includes(fieldId);
  }
  return Boolean(metadata.fields[fieldId]?.required);
}

/**
 * Fields shown in Create Jira UI: whitelisted slots plus any required field Jira mandates
 * that does not map to a slot (so creation cannot silently break).
 */
export function fieldsForCreateUi(metadata: JiraCreateMetadata): string[] {
  const slotToFieldId = new Map<CreateUiSlot, string>();
  const requiredOutsideWhitelist: string[] = [];

  Object.entries(metadata.fields).forEach(([fieldId, field]) => {
    if (CONTEXT_MANAGED_FIELD_IDS.has(fieldId)) return;
    const slot = resolveCreateUiSlot(field);
    if (slot) {
      if (!slotToFieldId.has(slot)) {
        slotToFieldId.set(slot, fieldId);
      }
      return;
    }
    if (isEffectivelyRequired(metadata, fieldId)) {
      requiredOutsideWhitelist.push(fieldId);
    }
  });

  const ordered = CREATE_UI_SLOT_ORDER.map((slot) => slotToFieldId.get(slot)).filter((id): id is string => Boolean(id));
  const extras = requiredOutsideWhitelist.filter((id) => !ordered.includes(id));
  return [...ordered, ...extras];
}

export function displayFieldLabel(field: ParsedJiraField): string {
  const label = normalizeLabel(field.label);
  if (label.includes("story point")) return "Story point";
  if (label === "development" || label.startsWith("development ")) return "Development efforts";
  return field.label;
}

export function fieldVariant(_field: ParsedJiraField): "jira-compact" {
  return "jira-compact";
}

export function fieldLayoutModifiers(field: ParsedJiraField): string[] {
  return field.id === "description" ? ["jira-field-multiline"] : [];
}

/** @deprecated tabs not used in streamlined Create Jira UI */
export function visibleJiraTabs(metadata: JiraCreateMetadata) {
  return metadata.sorted_tabs.filter((tab) => tab.fields.length > 0);
}

/** @deprecated use fieldsForCreateUi */
export function fieldsForRender(metadata: JiraCreateMetadata, _activeTabFieldIds?: string[]): string[] {
  return fieldsForCreateUi(metadata);
}
