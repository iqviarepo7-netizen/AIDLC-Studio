from __future__ import annotations

from ..config_loader import AppConfig, ModelRoute
from ..models import ComplexityAssessment, ModelOption, ModelRecommendation, ModelSelection


class ModelSelectorAgent:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def route_id(self, route: ModelRoute) -> str:
        return f"{route.provider}:{route.model}"

    def recommend(self, complexity: ComplexityAssessment) -> ModelRecommendation:
        selection = self.select(complexity)
        recommended_id = f"{selection.provider}:{selection.model}"
        alternatives: list[ModelOption] = []
        for route in self.config.policy.model_routing:
            route_key = self.route_id(route)
            alternatives.append(
                ModelOption(
                    id=route_key,
                    provider=route.provider,
                    model=route.model,
                    label=f"{route.provider} / {route.model}",
                    available=bool(route.model),
                    recommended=route_key == recommended_id,
                    estimated_tokens=route.max_tokens,
                )
            )
        return ModelRecommendation(recommended_model_id=recommended_id, alternatives=alternatives, reason=selection.reason)

    def select(self, complexity: ComplexityAssessment, retry_count: int = 0) -> ModelSelection:
        routes = sorted(self.config.policy.model_routing, key=lambda route: route.complexity_min)
        matching = [route for route in routes if route.complexity_min <= complexity.score <= route.complexity_max]
        if not matching:
            matching = routes[-1:] if routes else []

        if self.config.policy.retry_escalation == "next_tier" and retry_count:
            route = routes[min(retry_count, len(routes) - 1)] if routes else ModelRoute(
                complexity_min=1, complexity_max=10, provider="gemini", model="", max_tokens=8000
            )
        else:
            route = matching[0] if matching else ModelRoute(complexity_min=1, complexity_max=10, provider="gemini", model="", max_tokens=8000)

        reason = f"Recommended {route.provider}/{route.model} for complexity score {complexity.score} ({complexity.level})."
        if retry_count:
            reason += f" Retry {retry_count} escalated model tier."
        return ModelSelection(provider=route.provider, model=route.model, max_tokens=route.max_tokens, reason=reason)

    def selection_for_route(self, route_id: str) -> ModelSelection:
        for route in self.config.policy.model_routing:
            if self.route_id(route) == route_id:
                return ModelSelection(
                    provider=route.provider,
                    model=route.model,
                    max_tokens=route.max_tokens,
                    reason=f"User selected {route.provider}/{route.model}.",
                )
        raise ValueError(f"Unknown model route: {route_id}")

    def route_for_retry(self, current: ModelSelection, retry_count: int) -> ModelSelection:
        routes = self.config.policy.model_routing
        if not routes:
            return current
        current_index = next(
            (index for index, route in enumerate(routes) if route.model == current.model and route.provider == current.provider),
            0,
        )
        next_index = min(current_index + retry_count, len(routes) - 1)
        route = routes[next_index]
        return ModelSelection(
            provider=route.provider,
            model=route.model,
            max_tokens=route.max_tokens,
            reason=f"Escalated to {route.provider}/{route.model} on retry {retry_count}.",
        )
