from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .intent_cache import InMemoryIntentLibrary


class PlannerLike(Protocol):
    def plan(self, text: str, session: dict[str, Any]) -> dict[str, Any]:
        ...

    def is_confirm(self, text: str) -> bool:
        ...

    def is_cancel(self, text: str) -> bool:
        ...


@dataclass(slots=True)
class FlywheelRouterStats:
    total_requests: int = 0
    cache_hits: int = 0
    planner_calls: int = 0
    fallback_calls: int = 0
    learned_templates: int = 0

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.total_requests if self.total_requests else 0.0

    @property
    def planner_call_rate(self) -> float:
        return self.planner_calls / self.total_requests if self.total_requests else 0.0


class FlywheelIntentRouter:
    """Cache-first planner router for the runtime flywheel path."""

    def __init__(
        self,
        *,
        intent_library: InMemoryIntentLibrary,
        planner: PlannerLike,
        fallback_planner: PlannerLike | None = None,
        learn_guidance_intents: bool = True,
    ) -> None:
        self.intent_library = intent_library
        self.planner = planner
        self.fallback_planner = fallback_planner
        self.learn_guidance_intents = learn_guidance_intents
        self.stats = FlywheelRouterStats()

    def plan(self, text: str, session: dict[str, Any]) -> dict[str, Any]:
        self.stats.total_requests += 1

        match = self.intent_library.match(text, session)
        if match:
            self.stats.cache_hits += 1
            self._remember_route(
                session,
                source="cache",
                intent_label=match.template.intent_label,
                template_id=match.template.intent_id,
                similarity=match.similarity,
            )
            return match.plan

        try:
            self.stats.planner_calls += 1
            plan = self.planner.plan(text, session)
            source = "planner"
        except Exception as exc:
            if self.fallback_planner is None:
                raise
            self.stats.fallback_calls += 1
            plan = self.fallback_planner.plan(text, session)
            source = "fallback"
            session.setdefault("flywheel_errors", []).append({"input": text, "error": str(exc)})

        template_id = None
        suppress_learning = bool(session.pop("_suppress_flywheel_learning_once", False))
        if not suppress_learning and self._should_learn(plan):
            template = self.intent_library.learn(text, plan, session)
            template_id = template.intent_id
            self.stats.learned_templates = len(self.intent_library.all())

        self._remember_route(
            session,
            source=source,
            intent_label=plan.get("intent_label"),
            template_id=template_id,
            similarity=None,
        )
        return plan

    def is_confirm(self, text: str) -> bool:
        return self.planner.is_confirm(text) or bool(self.fallback_planner and self.fallback_planner.is_confirm(text))

    def is_cancel(self, text: str) -> bool:
        return self.planner.is_cancel(text) or bool(self.fallback_planner and self.fallback_planner.is_cancel(text))

    def snapshot(self) -> dict[str, Any]:
        return {
            "total_requests": self.stats.total_requests,
            "cache_hits": self.stats.cache_hits,
            "planner_calls": self.stats.planner_calls,
            "fallback_calls": self.stats.fallback_calls,
            "learned_templates": self.stats.learned_templates,
            "cache_hit_rate": self.stats.cache_hit_rate,
            "planner_call_rate": self.stats.planner_call_rate,
            "template_count": len(self.intent_library.all()),
        }

    def _should_learn(self, plan: dict[str, Any]) -> bool:
        if not plan.get("special"):
            return True
        return self.learn_guidance_intents and plan.get("intent_label") in {"help", "defer"}

    def _remember_route(
        self,
        session: dict[str, Any],
        *,
        source: str,
        intent_label: str | None,
        template_id: str | None,
        similarity: float | None,
    ) -> None:
        session["_last_plan_route"] = {
            "source": source,
            "intent_label": intent_label,
            "template_id": template_id,
            "similarity": similarity,
        }
