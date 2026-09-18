import { useEffect, useState, type ReactNode } from "react";
import { SETUP_HELP, type SetupHelpId } from "./setupHelpContent";

type Props = {
  title: string;
  guideId: SetupHelpId;
  mode: "direct" | "mcp";
  onModeChange: (mode: "direct" | "mcp") => void;
  children: ReactNode;
};

export function SetupSection({ title, guideId, mode, onModeChange, children }: Props) {
  const [helpOpen, setHelpOpen] = useState(false);
  const guide = SETUP_HELP[guideId];

  useEffect(() => {
    setHelpOpen(false);
  }, [guideId]);

  return (
    <section className="setup-section">
      <div className="setup-section-head">
        <div className="setup-section-title">
          <h3>{title}</h3>
          <button type="button" className="setup-help-trigger" onClick={() => setHelpOpen((value) => !value)} aria-expanded={helpOpen}>
            ?
            <span>{helpOpen ? "Hide help" : "Help"}</span>
          </button>
        </div>
        <div className="setup-section-actions">
          <ModeToggle mode={mode} onChange={onModeChange} />
        </div>
      </div>
      {helpOpen && (
        <div className="setup-help-body" role="region" aria-label={`${guide.title} setup guide`}>
          <p className="setup-help-label">{guide.title}</p>
          <p className="setup-help-summary">{guide.summary}</p>
          <ol className="setup-help-steps">
            {guide.steps.map((step, index) => (
              <li key={step.title}>
                <strong>
                  {index + 1}. {step.title}
                </strong>
                <span>{step.detail}</span>
              </li>
            ))}
          </ol>
          {guide.tips?.map((tip) => (
            <p key={tip} className="setup-help-tip">
              Tip: {tip}
            </p>
          ))}
        </div>
      )}
      {children}
    </section>
  );
}

function ModeToggle({ mode, onChange }: { mode: "direct" | "mcp"; onChange: (mode: "direct" | "mcp") => void }) {
  return (
    <div className="mode-toggle">
      <button type="button" className={mode === "direct" ? "active" : ""} onClick={() => onChange("direct")}>
        Direct
      </button>
      <button type="button" className={mode === "mcp" ? "active" : ""} onClick={() => onChange("mcp")}>
        MCP
      </button>
    </div>
  );
}
