from __future__ import annotations

import json
import re
from dataclasses import dataclass

from fastapi import HTTPException

from ..config_loader import AppConfig
from ..llm import LLMProvider
from ..models import JiraTask, Plan, RepositoryAnalysis


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str


class ImplementationAgent:
    def __init__(self, config: AppConfig, provider: LLMProvider) -> None:
        self.config = config
        self.provider = provider
        self.settings = config.agents.agents.get("implementation", {})

    def build_prompt(self, task: JiraTask, plan: Plan, repository: RepositoryAnalysis) -> str:
        template_path = self.settings.get("prompt_template_path", "prompts/implementation.txt")
        template = self.config.load_prompt(template_path)
        return template.format(
            key=task.key,
            summary=task.summary,
            description=task.description or "No additional description.",
            plan_json=plan.model_dump_json(),
            project_type=repository.project_type,
            relevant_files=", ".join(repository.relevant_files),
        )

    async def generate(self, task: JiraTask, plan: Plan, repository: RepositoryAnalysis) -> tuple[list[GeneratedFile], str]:
        prompt = self.build_prompt(task, plan, repository)
        raw = await self.provider.generate(prompt)
        payload = self._parse(raw)
        files = payload.get("files")
        summary = payload.get("summary")
        max_files = int(self.settings.get("max_files", 10))
        if not isinstance(files, list) or not files or len(files) > max_files or not isinstance(summary, str):
            raise HTTPException(status_code=502, detail="Implementation model returned an invalid response.")
        generated: list[GeneratedFile] = []
        max_bytes = self.config.policy.guardrails.max_file_bytes
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
                raise HTTPException(status_code=502, detail="Implementation model returned an invalid file change.")
            if len(item["content"].encode("utf-8")) > max_bytes:
                raise HTTPException(status_code=502, detail="Implementation model returned a file exceeding the configured size limit.")
            generated.append(GeneratedFile(path=item["path"], content=item["content"]))
        return generated, summary.strip()

    @staticmethod
    def _parse(raw: str) -> dict[str, object]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="Implementation model did not return valid JSON.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Implementation model response must be an object.")
        return payload
