export type SetupHelpGuide = {
  title: string;
  summary: string;
  steps: { title: string; detail: string }[];
  tips?: string[];
};

export type SetupHelpId = "jira-direct" | "jira-mcp" | "git-direct" | "git-mcp";

export const SETUP_HELP: Record<SetupHelpId, SetupHelpGuide> = {
  "jira-direct": {
    title: "Jira · Direct API",
    summary: "Connect to Jira Cloud or Server/Data Center using email and an API token or personal access token.",
    steps: [
      { title: "Create a token", detail: "Cloud: id.atlassian.com → Security → API tokens. Server/Data Center: Profile → Personal Access Tokens." },
      { title: "Set Base URL", detail: "Use the site root, e.g. https://your-company.atlassian.net or https://jira.company.com (no trailing path)." },
      { title: "Enter email + token", detail: "Use the account email and paste the token. Do not include extra characters from the copy." },
      { title: "Optional transition ID", detail: "Find it via Jira workflow settings if you want tickets moved to Done after publish." },
    ],
    tips: ["The studio tries REST API v3 then v2, and Basic auth then Bearer PAT, so Cloud and company Jira both work."],
  },
  "jira-mcp": {
    title: "Jira · MCP",
    summary: "Route Jira calls through an external MCP server that exposes Jira tools.",
    steps: [
      { title: "Start your Jira MCP server", detail: "Run the MCP process locally or on a reachable host/port." },
      { title: "Copy the MCP URL", detail: "Example: http://localhost:9001/jira — must expose a tools/call endpoint." },
      { title: "Add auth token if required", detail: "Some servers expect Bearer token in the Authorization header." },
      { title: "Map tools in policy.yaml", detail: "Backend expects fetch_issue, transition, and comment tool names (configured server-side)." },
      { title: "Validate connection", detail: "Click Validate & Connect — the studio pings the MCP endpoint before continuing." },
    ],
    tips: ["Direct mode is simpler for demos; MCP is better when Jira access is already centralized."],
  },
  "git-direct": {
    title: "Git · Direct (local)",
    summary: "Use a local git clone on this machine. Branch, commit, and push run via git CLI.",
    steps: [
      { title: "Clone the repository", detail: "git clone <url> and note the full path to the folder." },
      { title: "Set Repository path", detail: "Paste the absolute path, e.g. C:/projects/my-repo or /home/user/repo." },
      { title: "Choose base branch", detail: "Usually main or develop — used when creating feature branches and PRs." },
      { title: "Confirm remote name", detail: "Default is origin. Run git remote -v if unsure." },
      { title: "GitHub token (optional)", detail: "Needed only to create pull requests via GitHub API after push." },
    ],
    tips: ["Git must be installed and on PATH. The repo should already have remotes configured."],
  },
  "git-mcp": {
    title: "Git · MCP",
    summary: "Delegate analyze, branch, write, push, and PR actions to a Git MCP server.",
    steps: [
      { title: "Start your Git MCP server", detail: "Run the MCP service that wraps git/GitHub operations." },
      { title: "Copy the MCP URL", detail: "Example: http://localhost:9002/git" },
      { title: "Set local repository path", detail: "Even in MCP mode, the studio needs the clone path for branch listing and validation." },
      { title: "Add MCP token if required", detail: "Bearer token for secured MCP endpoints." },
      { title: "Ensure tool contract", detail: "Server should support analyze_repository, create_branch, write_files, push_branch, create_pull_request." },
    ],
    tips: ["MCP mode still uses the local path for branch discovery; MCP handles write/publish operations."],
  },
};

export function helpIdForJira(mode: "direct" | "mcp"): SetupHelpId {
  return mode === "direct" ? "jira-direct" : "jira-mcp";
}

export function helpIdForGit(mode: "direct" | "mcp"): SetupHelpId {
  return mode === "direct" ? "git-direct" : "git-mcp";
}
