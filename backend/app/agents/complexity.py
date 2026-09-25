from __future__ import annotations

import json
import re

from fastapi import HTTPException

from ..config_loader import AppConfig
from ..llm import LLMProvider
from ..models import ComplexityAssessment, JiraTask, RepositoryAnalysis


class ComplexityAgent:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.rules = config.agents.agents.get("complexity", {})

    async def assess(
        self,
        task: JiraTask,
        repository: RepositoryAnalysis | None = None,
        provider: LLMProvider | None = None,
    ) -> ComplexityAssessment:
        baseline = self._assess_keywords(task, repository)
        if not self.rules.get("use_llm") or provider is None or repository is None:
            return baseline
        try:
            return await self._assess_with_llm(task, repository, provider, baseline)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, HTTPException):
            return baseline

    def _assess_keywords(self, task: JiraTask, repository: RepositoryAnalysis | None) -> ComplexityAssessment:
        text = f"{task.summary} {task.description or ''}".lower()
        score = int(self.rules.get("base_score", 2))
        for rule in self.rules.get("keyword_rules", []):
            keywords = rule.get("keywords", [])
            if any(keyword in text for keyword in keywords):
                score += int(rule.get("score_add", 0))
        if repository and repository.relevant_files:
            overlap = sum(1 for path in repository.relevant_files if any(token in path.lower() for token in text.split() if len(token) > 3))
            score += min(overlap, 2)
        score = min(score, 10)
        level, estimated_files = self._level_for_score(score)
        template = self.rules.get("explanation_template", "{level} complexity based on configured rules and repository scope.")
        return ComplexityAssessment(
            score=score,
            level=level,
            estimated_files=estimated_files,
            explanation=template.format(level=level.title()),
        )

    async def _assess_with_llm(
        self,
        task: JiraTask,
        repository: RepositoryAnalysis,
        provider: LLMProvider,
        baseline: ComplexityAssessment,
    ) -> ComplexityAssessment:
        template_path = self.rules.get("prompt_template_path", "prompts/complexity.txt")
        template = self.config.load_prompt(template_path)
        prompt = template.format(
            key=task.key,
            summary=task.summary,
            description=task.description or "No additional description.",
            acceptance_criteria=", ".join(task.acceptance_criteria) or "Not specified",
            project_type=repository.project_type,
            relevant_files=", ".join(repository.relevant_files[:20]),
            file_count=len(repository.relevant_files),
        )
        raw = await provider.generate(prompt)
        payload = self._parse_json(raw)
        score = int(payload.get("score", baseline.score))
        score = max(1, min(score, 10))
        level = str(payload.get("level") or self._level_for_score(score)[0]).upper()
        if level not in {"LOW", "MEDIUM", "HIGH"}:
            level, _ = self._level_for_score(score)
        estimated_files = int(payload.get("estimated_files") or self._level_for_score(score)[1])
        explanation = str(payload.get("explanation") or baseline.explanation)
        likely_areas = payload.get("likely_areas")
        if isinstance(likely_areas, list) and likely_areas:
            explanation = f"{explanation} Likely areas: {', '.join(str(area) for area in likely_areas[:5])}."
        return ComplexityAssessment(score=score, level=level, estimated_files=estimated_files, explanation=explanation)

    def _level_for_score(self, score: int) -> tuple[str, int]:
        for level_rule in self.rules.get("levels", []):
            if score <= int(level_rule.get("max_score", 10)):
                return str(level_rule.get("name", "HIGH")), int(level_rule.get("estimated_files", 3))
        return "HIGH", 5

    @staticmethod
    def _parse_json(raw: str) -> dict[str, object]:
        from ..llm_json import parse_llm_json_object

        return parse_llm_json_object(raw, context="Complexity model")
