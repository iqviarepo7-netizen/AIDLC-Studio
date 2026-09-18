from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BranchSuggestion:
    suggested_work_branch: str
    existing_branches: list[str]
    branch_collision: bool
    collision_message: str | None


def list_branches(repository_path: str) -> list[str]:
    path = Path(repository_path).expanduser().resolve()
    if not path.is_dir():
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "branch", "-a", "--format=%(refname:short)"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []
    branches: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip().removeprefix("origin/").strip()
        if not name or name == "HEAD" or name.endswith("/HEAD"):
            continue
        if name not in branches:
            branches.append(name)
    return sorted(branches)


def normalize_work_branch(jira_key: str, summary: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", summary.lower()).strip("-")[:40]
    key = jira_key.lower()
    return f"ai/{key}-{slug}" if slug else f"ai/{key}"


def matching_branches(branches: list[str], jira_key: str) -> list[str]:
    prefix = f"ai/{jira_key.lower()}"
    matches = [branch for branch in branches if branch == prefix or branch.startswith(f"{prefix}-") or branch.startswith(f"{prefix}_")]
    return sorted(set(matches))


def suggest_work_branch(jira_key: str, summary: str, branches: list[str]) -> BranchSuggestion:
    base_name = normalize_work_branch(jira_key, summary)
    existing = matching_branches(branches, jira_key)
    if base_name not in branches and not existing:
        return BranchSuggestion(base_name, [], False, None)

    taken = set(existing)
    if base_name in branches:
        taken.add(base_name)

    suffix = 1
    while True:
        candidate = f"{base_name}_v{suffix}"
        if candidate not in branches and candidate not in taken:
            message = (
                f"Work branch `{base_name}` already exists."
                f" A new branch `{candidate}` will be created from the selected base branch."
            )
            return BranchSuggestion(candidate, sorted(taken), True, message)
        suffix += 1


def resolve_base_branch(requested: str | None, branches: list[str], configured_default: str | None = None) -> str:
    if requested:
        normalized = requested.removeprefix("origin/").strip()
        if normalized in branches:
            return normalized
    if configured_default:
        normalized = configured_default.removeprefix("origin/").strip()
        if normalized in branches:
            return normalized
    for candidate in ("main", "master", "develop"):
        if candidate in branches:
            return candidate
    return branches[0] if branches else (configured_default or "main")
