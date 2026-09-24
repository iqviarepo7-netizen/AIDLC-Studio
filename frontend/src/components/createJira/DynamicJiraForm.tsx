import { useMemo } from "react";

import type { JiraCreateMetadata, JiraFieldErrors, JiraFormValues, PendingIssueLink, PendingJiraAttachment } from "../../types/jiraCreate";

import { DynamicField } from "./DynamicField";

import { JiraAttachments } from "./JiraAttachments";

import { JiraLinkedWorkItems } from "./JiraLinkedWorkItems";

import { fieldLayoutModifiers, fieldVariant, fieldsForCreateUi } from "./jiraFormLayout";



type Props = {

  projectId?: string;

  metadata?: JiraCreateMetadata;

  values: JiraFormValues;

  errors: JiraFieldErrors;

  loading: boolean;

  loadError?: string;

  creating: boolean;

  attachments: PendingJiraAttachment[];

  onAttachmentsChange: (attachments: PendingJiraAttachment[]) => void;

  issueLinks: PendingIssueLink[];

  onIssueLinksChange: (links: PendingIssueLink[]) => void;

  onChange: (fieldId: string, value: unknown, userEdited?: boolean) => void;

  onCancel: () => void;

  onCreate: () => void;

};



export function DynamicJiraForm({

  projectId,

  metadata,

  values,

  errors,

  loading,

  loadError,

  creating,

  attachments,

  onAttachmentsChange,

  issueLinks,

  onIssueLinksChange,

  onChange,

  onCancel,

  onCreate,

}: Props) {

  const fieldIds = useMemo(() => (metadata ? fieldsForCreateUi(metadata) : []), [metadata]);



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



  const showAttachments = metadata.attachment_config?.enabled ?? true;



  return (

    <section className="create-jira-form jira-create-surface" aria-label="Create Jira form">

      <div className="panel-title">Create Jira</div>



      <div className="jira-create-scroll" role="tabpanel">

        <div className="jira-create-field-list">

          {fieldIds.map((fieldId) => {

            const field = metadata.fields[fieldId];

            if (!field) return null;

            return (

              <DynamicField

                key={field.id}

                field={field}

                value={values[field.id]}

                error={errors[field.id]}

                projectId={projectId}

                variant={fieldVariant(field)}
                layoutModifiers={fieldLayoutModifiers(field)}

                onChange={(id, value) => onChange(id, value, true)}

              />

            );

          })}

        </div>

        {showAttachments && (

          <JiraAttachments attachments={attachments} disabled={creating} onChange={onAttachmentsChange} />

        )}

        <JiraLinkedWorkItems projectId={projectId} links={issueLinks} disabled={creating} onChange={onIssueLinksChange} />

      </div>



      <div className="create-jira-footer">

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


