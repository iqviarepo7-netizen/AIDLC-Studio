from __future__ import annotations

import json
import re

from fastapi import HTTPException

from ..config_loader import AppConfig
from ..llm import LLMProvider
from ..models import JiraTask, Plan, RepositoryAnalysis, ScopeAnalysis


class PlanningAgent:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.rules = config.agents.agents.get("planning", {})

    async def plan(
        self,
        task: JiraTask,
        repository: RepositoryAnalysis | None,
        version: int = 1,
        scope_analysis: ScopeAnalysis | None = None,
        provider: LLMProvider | None = None,
    ) -> Plan:
        baseline = self._template_plan(task, repository, version, scope_analysis)
        if not self.rules.get("use_llm") or provider is None or repository is None:
            return baseline
        try:
            return await self._plan_with_llm(task, repository, version, scope_analysis, provider, baseline)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, HTTPException):
            return baseline

    def _template_plan(
        self,
        task: JiraTask,
        repository: RepositoryAnalysis | None,
        version: int,
        scope_analysis: ScopeAnalysis | None,
    ) -> Plan:
        risks = ["Confirm endpoint naming and response shape against existing conventions."]
        change_request = scope_analysis.pattern_summary if scope_analysis else None
        if scope_analysis and scope_analysis.already_implemented:
            reason = scope_analysis.already_implemented_reason or "The requested behavior may already exist."
            risks.insert(0, f"Possible duplicate work: {reason}")
        return Plan(
            version=version,
            objective=task.summary,
            affected_components=["Target application API", "Target application tests"],
            likely_files=repository.relevant_files[:4] if repository and repository.relevant_files else ["Existing route/controller module", "Existing test module"],
            implementation_steps=[
                "Inspect the matching application route and test conventions.",
                "Create the smallest implementation matching the accepted requirement.",
                "Add focused unit coverage and run the configured validation commands.",
            ],
            test_approach=[
                "Add a positive behavior test.",
                "Add an invalid-input or error-path test when the endpoint has inputs.",
            ],
            risks=risks,
            expected_result="The ticket behavior is implemented, validated, and ready for review.",
            change_request=change_request,
        )

    async def _plan_with_llm(
        self,
        task: JiraTask,
        repository: RepositoryAnalysis,
        version: int,
        scope_analysis: ScopeAnalysis | None,
        provider: LLMProvider,
        baseline: Plan,
    ) -> Plan:
        prompt = self.build_prompt(task, repository, scope_analysis)
        raw = await provider.generate(prompt)
        payload = self._parse_json(raw)
        plan = Plan(
            version=version,
            objective=str(payload.get("objective") or baseline.objective),
            affected_components=self._string_list(payload.get("affected_components"), baseline.affected_components),
            likely_files=self._string_list(payload.get("likely_files"), baseline.likely_files),
            implementation_steps=self._string_list(payload.get("implementation_steps"), baseline.implementation_steps),
            test_approach=self._string_list(payload.get("test_approach"), baseline.test_approach),
            risks=self._string_list(payload.get("risks"), baseline.risks),
            expected_result=str(payload.get("expected_result") or baseline.expected_result),
            change_request=str(payload["change_request"]) if payload.get("change_request") else baseline.change_request,
        )
        if not plan.implementation_steps:
            raise ValueError("Plan must include implementation steps.")
        return plan

    def build_prompt(
        self,
        task: JiraTask,
        repository: RepositoryAnalysis | None,
        scope_analysis: ScopeAnalysis | None = None,
    ) -> str:
        template_path = self.rules.get("prompt_template_path", "prompts/planning.txt")
        template = self.config.load_prompt(template_path)
        return template.format(
            key=task.key,
            summary=task.summary,
            description=task.description or "No additional description.",
            acceptance_criteria=", ".join(task.acceptance_criteria) or "Not specified",
            project_type=repository.project_type if repository else "Git repository",
            relevant_files=", ".join(repository.relevant_files[:20] if repository else []),
            relevant_directories=", ".join(repository.relevant_directories[:10] if repository else []),
            scope_summary=scope_analysis.pattern_summary if scope_analysis else "Not analyzed",
            change_type=scope_analysis.change_type.replace("_", " ") if scope_analysis else "Unknown",
            related_files=", ".join(scope_analysis.related_files[:10] if scope_analysis and scope_analysis.related_files else []),
        )

    @staticmethod
    def _string_list(value: object, fallback: list[str]) -> list[str]:
        if not isinstance(value, list):
            return fallback
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or fallback

    @staticmethod
    def _parse_json(raw: str) -> dict[str, object]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise ValueError("Planning response must be an object.")
        return payload
