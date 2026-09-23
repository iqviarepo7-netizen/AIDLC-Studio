import { useEffect } from "react";
import { ImplementationReportPanel } from "./ImplementationReportPanel";
import type { Workflow } from "../types";

type Props = {
  workflow: Workflow;
  open: boolean;
  onClose: () => void;
  onSelectFile?: (path: string) => void;
};

export function ImplementationReportModal({ workflow, open, onClose, onSelectFile }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="report-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="report-modal-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="report-modal">
        <ImplementationReportPanel workflow={workflow} onClose={onClose} onSelectFile={onSelectFile} />
      </div>
    </div>
  );
}

export default ImplementationReportModal;
