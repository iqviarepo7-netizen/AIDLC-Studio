from __future__ import annotations

from ..config_loader import AppConfig
from ..models import Workflow
from ..terminal_runner import TerminalRunner


class ValidatorAgent:
    def __init__(self, config: AppConfig, runner: TerminalRunner) -> None:
        self.runner = runner

    def validate(self, workflow: Workflow, repository_path: str) -> tuple[bool, str]:
        passed, entries = self.runner.run(repository_path)
        workflow.terminal_log.extend(entries)
        summary = "\n\n".join(entry.output for entry in entries if entry.output)
        return passed, summary or "Validation completed."
