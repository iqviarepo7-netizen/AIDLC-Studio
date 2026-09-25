import { createPortal } from "react-dom";

export type JiraCreatedToastState = {
  key: string;
  browseUrl?: string | null;
  partial?: boolean;
  detail?: string;
};

type Props = {
  toast: JiraCreatedToastState;
  onDismiss: () => void;
};

export function JiraCreatedToast({ toast, onDismiss }: Props) {
  const keyNode = toast.browseUrl ? (
    <a href={toast.browseUrl} target="_blank" rel="noopener noreferrer" className="jira-created-toast-key">
      {toast.key}
    </a>
  ) : (
    <span className="jira-created-toast-key">{toast.key}</span>
  );

  return createPortal(
    <div className="app-toast-stack" aria-live="polite">
      <div className="app-toast jira-created-toast" role="status">
        <div className="jira-created-toast-icon" aria-hidden>
          ✓
        </div>
        <div className="jira-created-toast-body">
          <p className="jira-created-toast-title">
            {toast.partial ? "Jira created with warnings" : "Jira created successfully"}
          </p>
          {keyNode}
          {toast.partial && (
            <p className="jira-created-toast-detail">
              {toast.detail ?? "Some additional operations could not be completed."}
            </p>
          )}
        </div>
        <button type="button" className="app-toast-dismiss ghost small" aria-label="Dismiss notification" onClick={onDismiss}>
          ×
        </button>
      </div>
    </div>,
    document.body,
  );
}
