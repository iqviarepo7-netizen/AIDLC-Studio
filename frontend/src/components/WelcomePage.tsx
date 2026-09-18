type Props = {
  appName?: string;
  tagline?: string;
  onEnter: () => void;
};

export function WelcomePage({ appName = "AIDLC Studio", tagline = "Agentic delivery from Jira to pull request", onEnter }: Props) {
  return (
    <div className="welcome-screen">
      <div className="welcome-grid" aria-hidden="true" />
      <div className="welcome-content">
        <p className="eyebrow">Virtual Development Environment</p>
        <h1>{appName}</h1>
        <p className="welcome-copy">{tagline}</p>
        <p className="muted">Configure Jira and Git for this session, then run the agent pipeline in an IDE-style workspace.</p>
        <button className="welcome-enter" onClick={onEnter}>
          Enter Development Space
        </button>
      </div>
      <pre className="welcome-snippet" aria-hidden="true">{`// boot sequence pending
import { agent } from "@aidlc/core";
await agent.connect({ jira, git });`}</pre>
    </div>
  );
}
