from __future__ import annotations

from typing import Any, Protocol

from .executor import EntityNotFoundError, PlanExecutionError, PlanExecutor
from .followup_feedback import classify_followup
from .intent_cache import InMemoryIntentLibrary
from .response_generator import ResponseGenerator


class IntentPlanner(Protocol):
    def plan(self, text: str, session: dict[str, Any]) -> dict[str, Any]:
        ...

    def is_confirm(self, text: str) -> bool:
        ...

    def is_cancel(self, text: str) -> bool:
        ...


class InteractionBackend:
    def __init__(
        self,
        executor: PlanExecutor,
        response_generator: ResponseGenerator,
        intent_planner: IntentPlanner,
        intent_library: InMemoryIntentLibrary | None = None,
    ) -> None:
        self.executor = executor
        self.response_generator = response_generator
        self.intent_planner = intent_planner
        self.intent_library = intent_library

    def process_message(self, user_input: str, session: dict[str, Any]) -> dict[str, Any]:
        text = user_input.strip()
        self._append_history(session, "user", text)
        pending_action = bool(session.get("pending_action_plan"))

        if self.intent_planner.is_confirm(text) and pending_action:
            pending_plan = session.pop("pending_action_plan")
            response = self.process_action(pending_plan, session)
            self._remember_response(session, response)
            self._remember_last_turn(session, text, pending_plan, response, plan_source="confirmed_action")
            self._append_history(session, "system", response.get("message", "已处理。"))
            return response

        if self.intent_planner.is_cancel(text) and pending_action:
            session.pop("pending_action_plan", None)
            response = self.response_generator.generate_guidance(
                "已取消，当前任务没有变化。",
                ["查看今天的待处理事项", "继续看当前客户"],
                session.get("selectable_items", []),
            )
            self._remember_response(session, response)
            session["last_turn"] = {
                "user_input": text,
                "intent_label": "cancel",
                "op_class": "read",
                "plan_source": "pending_action_cancel",
                "template_id": None,
                "similarity": None,
                "view_type": response["view"]["type"],
            }
            self._append_history(session, "system", response["message"])
            return {"status": "ok", **response, "session_id": session.get("session_id")}

        self._record_followup_feedback(text, session)

        plan = self.intent_planner.plan(text, session)
        response = self.process_plan(plan, session)
        if response.get("view", {}).get("type") == "ConfirmCard":
            options = response["view"]["data"].get("options", [])
            primary = next((option for option in options if option.get("plan")), None)
            if primary:
                session["pending_action_plan"] = primary["plan"]

        self._remember_response(session, response)
        self._remember_last_turn(session, text, plan, response)
        self._append_history(session, "system", response.get("message", ""))
        return {"status": "ok", **response, "session_id": session.get("session_id")}

    def process_plan(self, plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        if plan.get("special") == "reference_unresolvable":
            return self.response_generator.generate_guidance(
                plan.get("message", "没找到你说的那条记录。"),
                plan.get("options", []),
                plan.get("selectable_items", []),
            )
        if plan.get("special") == "reopen_unavailable":
            return self.response_generator.generate_guidance(
                plan.get("message", "当前状态不支持撤销。"),
                ["查看今天的待处理事项"],
            )

        if plan.get("op_class") == "write":
            return self.response_generator.generate_confirm_card(plan, session)

        try:
            executor_result = self.executor.execute(plan)
        except EntityNotFoundError as exc:
            return self.response_generator.generate_guidance(
                f"没找到你说的实体：{exc}",
                ["查看今天的待处理事项", "查一个具体客户的情况"],
            )
        except PlanExecutionError as exc:
            return self.response_generator.generate_guidance(
                f"执行失败：{exc}",
                ["查看今天的待处理事项"],
            )

        return self.response_generator.generate(executor_result, session)

    def process_action(self, plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        try:
            self.executor.execute(plan)
        except PlanExecutionError as exc:
            return {
                "status": "action_failed",
                "error_type": "cli_execution_failed",
                "message": str(exc),
                "view": None,
                "session_id": session.get("session_id"),
            }

        follow_up_result = self.executor.execute(
            {
                "plan": [
                    {
                        "step_id": "s1",
                        "type": "cli_call",
                        "cli_group": "today",
                        "cli_command": "today",
                        "args": {"tenant_id": session["tenant_id"], "limit": 5, "enrich": True},
                    }
                ],
                "intent_label": "today",
                "op_class": "read",
            }
        )
        response = self.response_generator.generate(follow_up_result, session)
        return {
            "status": "ok",
            **response,
            "session_id": session.get("session_id"),
        }

    def _remember_response(self, session: dict[str, Any], response: dict[str, Any]) -> None:
        view = response.get("view") or {}
        session["current_view"] = view
        session["selectable_items"] = view.get("selectable_items", [])
        session["state_summary"] = response.get("state_summary")

    def _append_history(self, session: dict[str, Any], actor: str, text: str) -> None:
        history = session.setdefault("history_window", [])
        history.append({"actor": actor, "text": text})
        del history[:-20]

    def _remember_last_turn(
        self,
        session: dict[str, Any],
        user_input: str,
        plan: dict[str, Any],
        response: dict[str, Any],
        plan_source: str | None = None,
    ) -> None:
        route = session.pop("_last_plan_route", {})
        session["last_turn"] = {
            "user_input": user_input,
            "intent_label": plan.get("intent_label"),
            "op_class": plan.get("op_class"),
            "plan_source": plan_source or route.get("source"),
            "template_id": route.get("template_id"),
            "similarity": route.get("similarity"),
            "view_type": (response.get("view") or {}).get("type"),
        }

    def _record_followup_feedback(self, user_input: str, session: dict[str, Any]) -> None:
        last_turn = session.get("last_turn")
        classification = classify_followup(last_turn, user_input)
        if classification.signal == "none":
            return

        event = {
            "signal": classification.signal,
            "reason": classification.reason,
            "user_input": user_input,
            "previous_intent_label": (last_turn or {}).get("intent_label"),
            "template_id": (last_turn or {}).get("template_id"),
            "previous_plan_source": (last_turn or {}).get("plan_source"),
        }
        session.setdefault("flywheel_feedback_events", []).append(event)
        del session["flywheel_feedback_events"][:-50]

        if classification.signal == "correction":
            session["_suppress_flywheel_learning_once"] = True
            session.setdefault("flywheel_review_queue", []).append(event)
            del session["flywheel_review_queue"][:-50]
            session.pop("pending_action_plan", None)
            template_id = event.get("template_id")
            if self.intent_library is not None and template_id and self.intent_library.find_by_id(template_id):
                self.intent_library.record_feedback(
                    template_id,
                    is_correction=True,
                    user_input=user_input,
                    reason=classification.reason,
                )
        elif classification.signal == "missing_info":
            intent_label = event.get("previous_intent_label")
            if self.intent_library is not None and intent_label:
                self.intent_library.record_missing_field(intent_label, user_input, classification.reason)
