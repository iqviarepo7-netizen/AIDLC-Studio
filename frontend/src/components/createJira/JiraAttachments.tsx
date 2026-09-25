import type { PendingJiraAttachment } from "../../types/jiraCreate";

type Props = {
  attachments: PendingJiraAttachment[];
  disabled?: boolean;
  onChange: (attachments: PendingJiraAttachment[]) => void;
};

export function JiraAttachments({ attachments, disabled, onChange }: Props) {
  const addFiles = (files: FileList | null) => {
    if (!files || disabled) return;
    const next = [...attachments];
    Array.from(files).forEach((file) => {
      next.push({ id: `${file.name}-${file.size}-${file.lastModified}`, file });
    });
    onChange(next);
  };

  const removeAttachment = (id: string) => {
    onChange(attachments.filter((entry) => entry.id !== id));
  };

  return (
    <div className="jira-attachments jira-field jira-compact" data-field-id="attachment">
      <label htmlFor="jira-attachment-input">Attachment</label>
      <div className="jira-attachment-column">
        <div
          className="jira-attachment-drop"
          onDragOver={(event) => {
            event.preventDefault();
          }}
          onDrop={(event) => {
            event.preventDefault();
            addFiles(event.dataTransfer.files);
          }}
        >
          <input
            id="jira-attachment-input"
            type="file"
            multiple
            disabled={disabled}
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <p className="muted">Drop files here or browse</p>
        </div>
        {attachments.length > 0 && (
          <div className="jira-attachment-selected">
            <p className="jira-attachment-selected-title">Selected files:</p>
            <ul className="jira-attachment-list">
              {attachments.map((item) => (
                <li key={item.id}>
                  <span className="jira-attachment-file-icon" aria-hidden="true">📎</span>
                  <span className="jira-attachment-file-name">{item.file.name}</span>
                  <span className="jira-attachment-file-size">{formatBytes(item.file.size)}</span>
                  <button
                    type="button"
                    className="ghost small"
                    disabled={disabled}
                    onClick={() => removeAttachment(item.id)}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
