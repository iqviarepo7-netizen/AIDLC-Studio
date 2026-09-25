import { useEffect } from "react";
import { ModelConfigurationPanel } from "./ModelConfigurationPanel";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function ModelConfigurationModal({ open, onClose }: Props) {
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
      aria-labelledby="model-config-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="report-modal model-config-modal">
        <ModelConfigurationPanel onClose={onClose} />
      </div>
    </div>
  );
}
