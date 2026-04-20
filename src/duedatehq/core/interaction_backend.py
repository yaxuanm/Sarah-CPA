from __future__ import annotations

from typing import Any

from .executor import EntityNotFoundError, PlanExecutionError, PlanExecutor
from .response_generator import ResponseGenerator


class InteractionBackend:
    def __init__(self, executor: PlanExecutor, response_generator: ResponseGenerator) -> None:
        self.executor = executor
        self.response_generator = response_generator

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
