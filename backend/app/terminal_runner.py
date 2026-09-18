from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from time import perf_counter

from .config_loader import AppConfig
from .models import TerminalLogEntry


class TerminalRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def run(self, repository_path: str) -> tuple[bool, list[TerminalLogEntry]]:
        root = Path(repository_path).expanduser().resolve()
        entries: list[TerminalLogEntry] = []
        for command in self.config.policy.validation.commands:
            started = perf_counter()
            try:
                result = subprocess.run(
                    command.cmd,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=self.config.policy.validation.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                duration = int((perf_counter() - started) * 1000)
                output = exc.stderr or exc.stdout or "Command timed out."
                entries.append(
                    TerminalLogEntry(
                        command_id=command.id,
                        command=" ".join(command.cmd),
                        status="FAIL",
                        output=output,
                        duration_ms=duration,
                    )
                )
                return False, entries

            duration = int((perf_counter() - started) * 1000)
            output = (result.stdout + "\n" + result.stderr).strip()[-4000:]
            status = "PASS" if result.returncode == 0 else "FAIL"
            entries.append(
                TerminalLogEntry(
                    command_id=command.id,
                    command=" ".join(command.cmd),
                    status=status,
                    output=output or f"Command exited with code {result.returncode}.",
                    duration_ms=duration,
                )
            )
            if status == "FAIL" and self.config.policy.validation.fail_fast:
                return False, entries
        return True, entries

    def summarize(self, entries: list[TerminalLogEntry]) -> tuple[str, int, int, str, str]:
        passed = sum(1 for entry in entries if entry.status == "PASS")
        failed = sum(1 for entry in entries if entry.status == "FAIL")
        status = "PASS" if failed == 0 and passed > 0 else "FAIL" if failed else "BLOCKED"
        command = "; ".join(entry.command for entry in entries)
        summary = "\n".join(f"[{entry.command_id}] {entry.status}: {entry.output[:500]}" for entry in entries)
        return status, passed, failed, command, summary
