import { useEffect, useState } from "react";

const BOOT_LINES = [
  { text: "Initializing virtual dev shell...", delay: 0 },
  { text: "Mounting workspace filesystem...", delay: 500 },
  { text: "Loading syntax engines [TS, PY, GO]...", delay: 1000 },
  { text: "Spawning agent orchestrator...", delay: 1500 },
  { text: "Preparing Jira ↔ Git bridge...", delay: 2100 },
  { text: "Opening AIDLC Studio channel...", delay: 2700 },
];

type Props = {
  onComplete: () => void;
};

export function BootSequence({ onComplete }: Props) {
  const [visibleLines, setVisibleLines] = useState<string[]>([]);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const timers = BOOT_LINES.map((line) =>
      window.setTimeout(() => {
        setVisibleLines((current) => [...current, line.text]);
        setProgress((current) => Math.min(current + 100 / BOOT_LINES.length, 100));
      }, line.delay),
    );
    const done = window.setTimeout(onComplete, 3400);
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      window.clearTimeout(done);
    };
  }, [onComplete]);

  return (
    <div className="boot-screen">
      <div className="boot-portal">
        <div className="boot-ring ring-a" />
        <div className="boot-ring ring-b" />
        <div className="boot-core">
          <span>&lt;/&gt;</span>
        </div>
      </div>
      <div className="boot-panel">
        <div className="boot-panel-head">
          <span>aidlc-boot</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div className="boot-log">
          {visibleLines.map((line) => (
            <p key={line}>
              <span className="boot-prompt">›</span> {line}
            </p>
          ))}
          <p className="boot-cursor-line">
            <span className="boot-prompt">›</span> <span className="boot-cursor" />
          </p>
        </div>
        <div className="boot-progress">
          <div style={{ width: `${progress}%` }} />
        </div>
      </div>
      <div className="boot-matrix" aria-hidden="true">
        {Array.from({ length: 24 }).map((_, index) => (
          <span key={index} style={{ animationDelay: `${index * 0.12}s` }}>
            {["fn", "git", "pr", "ai", "mcp", "run", "tsx", "py"][index % 8]}
          </span>
        ))}
      </div>
    </div>
  );
}
