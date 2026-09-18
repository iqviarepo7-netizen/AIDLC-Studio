from __future__ import annotations

import re

from ..models import JiraTask, RepositoryAnalysis, ScopeAnalysis


class ScopeAnalyzerAgent:
    IMPLEMENTED_HINTS = ("already implemented", "already exists", "no changes needed", "nothing to do")
    EXTEND_HINTS = ("update", "extend", "modify", "refactor", "enhance", "fix", "bug", "regression")
    NEW_HINTS = ("add new", "create new", "introduce", "implement new", "new feature", "new endpoint")

    def analyze(self, task: JiraTask, repository: RepositoryAnalysis | None) -> ScopeAnalysis:
        text = " ".join(
            filter(
                None,
                [task.summary, task.description or "", " ".join(task.acceptance_criteria)],
            )
        ).lower()
        relevant_files = repository.relevant_files if repository else []
        relevant_dirs = repository.relevant_directories if repository else []
        related_files = self._related_files(text, relevant_files)

        if any(hint in text for hint in self.IMPLEMENTED_HINTS):
            return ScopeAnalysis(
                change_type="LIKELY_ALREADY_IMPLEMENTED",
                pattern_summary="Ticket text suggests the work may already be complete.",
                already_implemented=True,
                already_implemented_reason="Jira description mentions existing or completed work.",
                related_files=related_files,
            )

        if self._looks_already_implemented(text, relevant_files):
            return ScopeAnalysis(
                change_type="LIKELY_ALREADY_IMPLEMENTED",
                pattern_summary="Repository files appear to already cover the requested behavior.",
                already_implemented=True,
                already_implemented_reason="Matching route, handler, or test names were found in the repository analysis.",
                related_files=related_files,
            )

        if related_files or any(hint in text for hint in self.EXTEND_HINTS):
            return ScopeAnalysis(
                change_type="EXTEND_EXISTING",
                pattern_summary="This looks like a change to existing functionality in the repository.",
                already_implemented=False,
                related_files=related_files,
            )

        if any(hint in text for hint in self.NEW_HINTS) or not relevant_files:
            return ScopeAnalysis(
                change_type="NEW_FEATURE",
                pattern_summary="This looks like new functionality with limited overlap in the current codebase.",
                already_implemented=False,
                related_files=related_files,
            )

        notes = repository.notes.lower() if repository and repository.notes else ""
        project_type = repository.project_type.lower() if repository and repository.project_type else ""
        if relevant_dirs and ("existing" in notes or "extend" in notes):
            change_type = "EXTEND_EXISTING"
            summary = "Repository analysis indicates changes within existing project areas."
        else:
            change_type = "UNCLEAR"
            summary = "Scope could not be classified confidently; planning will inspect the repository conventions."

        return ScopeAnalysis(
            change_type=change_type,
            pattern_summary=summary,
            already_implemented=False,
            related_files=related_files,
        )

    @staticmethod
    def _related_files(text: str, relevant_files: list[str]) -> list[str]:
        tokens = {token for token in re.findall(r"[a-z][a-z0-9_-]{2,}", text) if token not in {"the", "and", "for", "with", "from", "that", "this", "ticket"}}
        matches: list[str] = []
        for path in relevant_files:
            normalized = path.lower().replace("\\", "/")
            if any(token in normalized for token in tokens):
                matches.append(path)
        return matches[:8]

    @staticmethod
    def _looks_already_implemented(text: str, relevant_files: list[str]) -> bool:
        endpoint_match = re.search(r"(?:endpoint|route|api)\s+[/\"]?([a-z0-9/_-]+)", text)
        if endpoint_match:
            needle = endpoint_match.group(1).strip("/").lower()
            if any(needle in path.lower() for path in relevant_files):
                return True
        function_match = re.search(r"(?:function|method|handler)\s+([a-z0-9_]+)", text)
        if function_match:
            needle = function_match.group(1).lower()
            if any(needle in path.lower() for path in relevant_files):
                return True
        return False
