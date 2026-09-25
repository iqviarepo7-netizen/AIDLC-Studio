import { useEffect, useRef, useState } from "react";
import type { JiraFieldOption } from "../../types/jiraCreate";

type Props = {
  id: string;
  value: string;
  options: JiraFieldOption[];
  required?: boolean;
  describedBy?: string;
  onChange: (value: string) => void;
};

export function ColorPickerField({ id, value, options, required, describedBy, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const selected = options.find((option) => String(option.value) === String(value));

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  return (
    <div className={`jira-color-picker${open ? " open" : ""}`} ref={rootRef}>
      <button
        type="button"
        id={id}
        className="jira-color-picker-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-describedby={describedBy}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="jira-color-swatch" style={{ background: swatchStyle(selected) }} aria-hidden />
        <span className="jira-color-picker-label">{selected?.label ?? "Select…"}</span>
        <span className="jira-color-picker-chevron" aria-hidden>
          ▾
        </span>
      </button>
      {open && (
        <div className="jira-color-picker-menu" role="listbox" aria-labelledby={id}>
          <div className="jira-color-picker-grid">
            {options.map((option) => {
              const isSelected = String(value) === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  className={isSelected ? "selected" : undefined}
                  title={option.label}
                  disabled={option.disabled}
                  onClick={() => {
                    onChange(option.value);
                    setOpen(false);
                  }}
                >
                  <span className="jira-color-swatch" style={{ background: swatchStyle(option) }} />
                  {isSelected && <span className="jira-color-check" aria-hidden>✓</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {required && !value && <span className="sr-only">Color selection is required</span>}
    </div>
  );
}

function swatchStyle(option?: JiraFieldOption): string {
  if (option?.swatch_color) return option.swatch_color;
  return "var(--border)";
}
