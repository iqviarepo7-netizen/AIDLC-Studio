from __future__ import annotations

from ..config_loader import AppConfig
from ..models import ComplexityAssessment, JiraTask, RequirementAnalysis


class TaskAnalyzerAgent:
    def __init__(self, config: AppConfig) -> None:
        self.config = config.agents.agents.get("task_analyzer", {})

    def analyze(self, task: JiraTask) -> RequirementAnalysis:
        default_acceptance = self.config.get("default_acceptance", "The behavior described by '{summary}' is available to callers.")
        criteria = task.acceptance_criteria or [default_acceptance.format(summary=task.summary)]
        ambiguity = []
        if not task.description:
            ambiguity.append(self.config.get("missing_description_ambiguity", "The ticket has no description beyond its summary."))
        return RequirementAnalysis(
            problem_summary=task.summary,
            functional_requirement=task.description or task.summary,
            acceptance_criteria=criteria,
            constraints=[self.config.get("default_constraint", "Preserve existing repository conventions.")],
            ambiguities=ambiguity,
        )
