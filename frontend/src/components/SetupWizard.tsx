import { useEffect, useState } from "react";
import { api } from "../api";
import type { GitConnectionConfig, JiraConnectionConfig, SetupRequest } from "../types";
import { helpIdForGit, helpIdForJira } from "./setupHelpContent";
import { SetupSection } from "./SetupSection";

type Props = {
  onSubmit: (payload: SetupRequest) => void;
  initial?: SetupRequest;
  busy?: boolean;
  error?: string;
};

const defaultJira: JiraConnectionConfig = { mode: "direct", base_url: "", email: "", api_token: "", mcp_url: "", mcp_token: "", transition_id: "" };
const defaultGit: GitConnectionConfig = { mode: "direct", repository_path: "", base_branch: "main", remote: "origin", mcp_url: "", mcp_token: "" };

function BranchField({
  repositoryPath,
  value,
  onChange,
}: {
  repositoryPath: string;
  value: string;
  onChange: (branch: string) => void;
}) {
  const [branches, setBranches] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [branchError, setBranchError] = useState<string>();

  useEffect(() => {
    const path = repositoryPath.trim();
    if (!path) {
      setBranches([]);
      setBranchError(undefined);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setBranchError(undefined);
    const timer = window.setTimeout(() => {
      api
        .previewBranches(path)
        .then((response) => {
          if (cancelled) return;
          setBranches(response.branches);
          if (!response.branches.includes(value)) {
            onChange(response.default_branch);
          }
        })
        .catch((cause) => {
          if (cancelled) return;
          setBranches([]);
          setBranchError(cause instanceof Error ? cause.message : "Could not load branches.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [repositoryPath, value, onChange]);

  if (branches.length > 0) {
    return (
      <label>
        Default base branch
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          {branches.map((branch) => (
            <option key={branch} value={branch}>
              {branch}
            </option>
          ))}
        </select>
      </label>
    );
  }

  return (
    <label>
      Default base branch
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={loading ? "Loading branches..." : "main"}
      />
      {branchError && <small className="warning-text">{branchError}</small>}
    </label>
  );
}

export function SetupWizard({ onSubmit, initial, busy, error }: Props) {
  // 1. Lazy initialization: Load from localStorage first, then fallback to initial props or defaults
  const [jira, setJira] = useState<JiraConnectionConfig>(() => {
    if (initial?.jira) return initial.jira;
    const saved = localStorage.getItem("setup_jira");
    return saved ? JSON.parse(saved) : defaultJira;
  });
 
  const [git, setGit] = useState<GitConnectionConfig>(() => {
    if (initial?.git) return initial.git;
    const saved = localStorage.getItem("setup_git");
    return saved ? JSON.parse(saved) : defaultGit;
  });
 
  // 2. Keep state in sync if the initial prop changes from a parent component
  useEffect(() => {
    if (initial) {
      setJira(initial.jira);
      setGit(initial.git);
    }
  }, [initial]);
 
  // 3. Automatically sync state changes to localStorage as the user types
  useEffect(() => {
    localStorage.setItem("setup_jira", JSON.stringify(jira));
  }, [jira]);
 
  useEffect(() => {
    localStorage.setItem("setup_git", JSON.stringify(git));
  }, [git]);
 
  return (
    <div className="setup-overlay">
      <form
        className="setup-modal"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit({ jira, git });
        }}
      >
        <h2>Connect Jira & Git</h2>
        {/* Updated descriptive text */}
        <p className="muted">Choose direct API access or MCP for each integration. Credentials stay in localStorage across browser sessions.</p>
        {error && <div className="banner error">{error}</div>}
 
        <SetupSection title="Jira" guideId={helpIdForJira(jira.mode)} mode={jira.mode} onModeChange={(mode) => setJira({ ...jira, mode })}>
          {jira.mode === "direct" ? (
            <div className="setup-grid">
              <label>
                Base URL
                <input value={jira.base_url ?? ""} onChange={(e) => setJira({ ...jira, base_url: e.target.value })} placeholder="https://your-org.atlassian.net" required />
              </label>
              <label>
                Email
                <input value={jira.email ?? ""} onChange={(e) => setJira({ ...jira, email: e.target.value })} placeholder="you@company.com" required />
              </label>
              <label>
                API token
                <input type="password" value={jira.api_token ?? ""} onChange={(e) => setJira({ ...jira, api_token: e.target.value })} required />
              </label>
              <label className="setup-field-full">
                Done transition ID (optional)
                <input value={jira.transition_id ?? ""} onChange={(e) => setJira({ ...jira, transition_id: e.target.value })} />
              </label>
            </div>
          ) : (
            <div className="setup-grid">
              <label>
                MCP URL
                <input value={jira.mcp_url ?? ""} onChange={(e) => setJira({ ...jira, mcp_url: e.target.value })} placeholder="http://localhost:9001/jira" required />
              </label>
              <label>
                MCP token (optional)
                <input type="password" value={jira.mcp_token ?? ""} onChange={(e) => setJira({ ...jira, mcp_token: e.target.value })} />
              </label>
              <label className="setup-field-full">
                Done transition ID (optional)
                <input value={jira.transition_id ?? ""} onChange={(e) => setJira({ ...jira, transition_id: e.target.value })} />
              </label>
            </div>
          )}
        </SetupSection>
 
        <SetupSection title="Git" guideId={helpIdForGit(git.mode)} mode={git.mode} onModeChange={(mode) => setGit({ ...git, mode })}>
          {git.mode === "direct" ? (
            <div className="setup-grid">
              <label>
                Repository path
                <input value={git.repository_path ?? ""} onChange={(e) => setGit({ ...git, repository_path: e.target.value })} placeholder="C:/projects/my-repo" required />
              </label>
              <BranchField
                repositoryPath={git.repository_path ?? ""}
                value={git.base_branch ?? "main"}
                onChange={(base_branch) => setGit({ ...git, base_branch })}
              />
              <label>
                Remote name
                <input value={git.remote ?? "origin"} onChange={(e) => setGit({ ...git, remote: e.target.value })} />
              </label>
              <label className="setup-field-full">
                GitHub token (optional, for PR creation)
                <input type="password" value={git.mcp_token ?? ""} onChange={(e) => setGit({ ...git, mcp_token: e.target.value })} />
              </label>
            </div>
          ) : (
            <div className="setup-grid">
              <label>
                MCP URL
                <input value={git.mcp_url ?? ""} onChange={(e) => setGit({ ...git, mcp_url: e.target.value })} placeholder="http://localhost:9002/git" required />
              </label>
              <label>
                MCP token (optional)
                <input type="password" value={git.mcp_token ?? ""} onChange={(e) => setGit({ ...git, mcp_token: e.target.value })} />
              </label>
              <label>
                Repository path
                <input value={git.repository_path ?? ""} onChange={(e) => setGit({ ...git, repository_path: e.target.value })} placeholder="Local clone path" required />
              </label>
              <BranchField
                repositoryPath={git.repository_path ?? ""}
                value={git.base_branch ?? "main"}
                onChange={(base_branch) => setGit({ ...git, base_branch })}
              />
            </div>
          )}
        </SetupSection>
 
        <div className="setup-actions">
          <button type="submit" disabled={busy}>
            {busy ? "Validating connections..." : "Validate & Connect"}
          </button>
        </div>
      </form>
    </div>
  );
}
