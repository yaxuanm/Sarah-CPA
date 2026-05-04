from __future__ import annotations

import re
from typing import Any, Protocol

from .agent_kernel import AgentKernel, AgentKernelDecision
from .executor import EntityNotFoundError, PlanExecutionError, PlanExecutor
from .followup_feedback import classify_followup
from .intent_cache import InMemoryIntentLibrary
from .models import DeadlineStatus
from .response_generator import ResponseGenerator
from .surface_composer import SurfaceComposer
from .system_state import record_operation, remember_response_state
from .workspace_registry import get_workspace_spec, workspace_allows_edits


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
        agent_kernel: AgentKernel | None = None,
    ) -> None:
        self.executor = executor
        self.response_generator = response_generator
        self.intent_planner = intent_planner
        self.intent_library = intent_library
        self.agent_kernel = agent_kernel
        self.surface_composer = SurfaceComposer(response_generator)

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
            self._remember_last_turn(
                session,
                text,
                {"intent_label": "cancel", "op_class": "read"},
                response,
                plan_source="pending_action_cancel",
            )
            self._append_history(session, "system", response["message"])
            return {"status": "ok", **response, "session_id": session.get("session_id")}

        self._record_followup_feedback(text, session)

        workspace_guard_response = self._guard_cross_workspace_request(text, session)
        if workspace_guard_response:
            self._remember_response(session, workspace_guard_response)
            self._remember_last_turn(
                session,
                text,
                {"intent_label": "cross_workspace_redirect", "op_class": "read"},
                workspace_guard_response,
                plan_source="workspace_guard",
            )
            self._append_history(session, "system", workspace_guard_response.get("message", ""))
            return {"status": "ok", **workspace_guard_response, "session_id": session.get("session_id")}

        if not self.agent_kernel:
            response = self._agent_unavailable_response("现在没有可用的 agent，所以我不能研判这个问题。")
            self._remember_response(session, response)
            self._remember_last_turn(
                session,
                text,
                {"intent_label": "agent_unavailable", "op_class": "read"},
                response,
                plan_source="agent_required",
            )
            self._append_history(session, "system", response.get("message", ""))
            return {"status": "ok", **response, "session_id": session.get("session_id")}

        kernel_decision = self.agent_kernel.decide(text, session)
        if not kernel_decision:
            reason = session.get("last_agent_error")
            detail = f"原因：{reason}" if reason else "没有返回具体错误。"
            response = self._agent_unavailable_response(f"agent 现在不可用，{detail} 我不会用规则或模板继续处理。")
            self._remember_response(session, response)
            self._remember_last_turn(
                session,
                text,
                {"intent_label": "agent_no_decision", "op_class": "read"},
                response,
                plan_source="agent_required",
            )
            self._append_history(session, "system", response.get("message", ""))
            return {"status": "ok", **response, "session_id": session.get("session_id")}

        kernel_response = self._answer_from_agent_decision(kernel_decision, text, session)
        if kernel_response:
            self._remember_response(session, kernel_response)
            session["last_agent_kernel"] = {
                "route": kernel_decision.route,
                "need_type": kernel_decision.need_type,
                "render_policy": kernel_decision.render_policy,
                "data_requests": kernel_decision.data_requests,
                "answer_mode": kernel_decision.answer_mode,
                "confidence": kernel_decision.confidence,
                "reason": kernel_decision.reason,
            }
            self._remember_last_turn(
                session,
                text,
                {"intent_label": kernel_decision.need_type, "op_class": "read"},
                kernel_response,
                plan_source="agent_kernel",
            )
            self._append_history(session, "system", kernel_response.get("message", ""))
            return {"status": "ok", **kernel_response, "session_id": session.get("session_id")}

        response = self._agent_unavailable_response("agent 没有给出可执行的对话或展示决策，我不会用规则或模板继续处理。")
        self._remember_response(session, response)
        self._remember_last_turn(
            session,
            text,
            {"intent_label": "agent_unhandled_decision", "op_class": "read"},
            response,
            plan_source="agent_required",
        )
        self._append_history(session, "system", response.get("message", ""))
        return {"status": "ok", **response, "session_id": session.get("session_id")}

    def _process_plan_turn(
        self,
        text: str,
        plan: dict[str, Any],
        session: dict[str, Any],
        *,
        plan_source: str | None = None,
    ) -> dict[str, Any]:
        response = self.process_plan(plan, session)
        if (response.get("view") or {}).get("type") == "ConfirmCard":
            options = response["view"]["data"].get("options", [])
            primary = next((option for option in options if option.get("plan")), None)
            if primary:
                session["pending_action_plan"] = primary["plan"]

        self._remember_response(session, response)
        self._remember_last_turn(session, text, plan, response, plan_source=plan_source)
        self._append_history(session, "system", response.get("message", ""))
        return {"status": "ok", **response, "session_id": session.get("session_id")}

    def _agent_unavailable_response(self, message: str) -> dict[str, Any]:
        return {
            "message": message,
            "view": None,
            "actions": [],
            "state_summary": "agent required",
            "secretary": {
                "reply": message,
                "action": {"type": "none"},
            },
        }

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
        if plan.get("special") == "render_spec_needed":
            return self.response_generator.generate_render_spec_surface(
                plan.get("user_input", ""),
                session,
                plan.get("message"),
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

    def process_direct_action(self, plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        return self._process_plan_turn("__direct_action__", plan, session, plan_source="direct_action")

    def process_direct_command(self, command: str, session: dict[str, Any]) -> dict[str, Any]:
        if command == "confirm_pending":
            pending_plan = session.pop("pending_action_plan", None)
            if not pending_plan:
                response = self.response_generator.generate_guidance(
                    "没有等待确认的操作，我没有改动任何数据。",
                    ["查看今天的待处理事项"],
                    session.get("selectable_items", []),
                )
                self._remember_response(session, response)
                self._remember_last_turn(
                    session,
                    "__confirm_pending__",
                    {"intent_label": "confirm_pending_missing", "op_class": "read"},
                    response,
                    plan_source="direct_action",
                )
                self._append_history(session, "system", response.get("message", ""))
                return {"status": "ok", **response, "session_id": session.get("session_id")}
            response = self.process_action(pending_plan, session)
            self._remember_response(session, response)
            self._remember_last_turn(session, "__confirm_pending__", pending_plan, response, plan_source="direct_action_confirm")
            self._append_history(session, "system", response.get("message", "已处理。"))
            return response

        if command == "cancel_pending":
            session.pop("pending_action_plan", None)
            response = self.response_generator.generate_guidance(
                "已取消，当前任务没有变化。",
                ["查看今天的待处理事项", "继续看当前客户"],
                session.get("selectable_items", []),
            )
            self._remember_response(session, response)
            self._remember_last_turn(
                session,
                "__cancel_pending__",
                {"intent_label": "cancel", "op_class": "read"},
                response,
                plan_source="direct_action_cancel",
            )
            self._append_history(session, "system", response.get("message", ""))
            return {"status": "ok", **response, "session_id": session.get("session_id")}

        response = self.response_generator.generate_guidance(
            "这个按钮命令暂时不可执行，我没有改动任何数据。",
            ["查看今天的待处理事项"],
            session.get("selectable_items", []),
        )
        self._remember_response(session, response)
        self._remember_last_turn(
            session,
            "__unknown_direct_command__",
            {"intent_label": "unknown_direct_command", "op_class": "read"},
            response,
            plan_source="direct_action",
        )
        self._append_history(session, "system", response.get("message", ""))
        return {"status": "ok", **response, "session_id": session.get("session_id")}

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

    def _client_deadline_plan(self, tenant_id: str, client_id: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "list",
                    "args": {"tenant_id": tenant_id, "client_id": client_id},
                }
            ],
            "intent_label": "client_deadline_list",
            "op_class": "read",
        }

    def _guard_cross_workspace_request(self, user_input: str, session: dict[str, Any]) -> dict[str, Any] | None:
        workspace = session.get("current_workspace") if isinstance(session.get("current_workspace"), dict) else {}
        workspace_type = workspace.get("type")
        if workspace_allows_edits(workspace_type):
            return None
        if workspace_type != "AuditWorkspace":
            return None
        if not self._looks_like_due_date_edit(user_input):
            return None

        selectable = session.get("selectable_items") or []
        selected = selectable[0] if selectable and isinstance(selectable[0], dict) else {}
        client_id = selected.get("client_id")
        actions: list[dict[str, Any]] = []
        if client_id and session.get("tenant_id"):
            actions.append(
                {
                    "label": "回到客户工作区",
                    "action": {
                        "type": "direct_execute",
                        "expected_view": "ClientCard",
                        "plan": self._client_deadline_plan(session["tenant_id"], client_id),
                    },
                }
            )
        if selected.get("deadline_id") and session.get("tenant_id"):
            actions.append(
                {
                    "label": "继续查看依据",
                    "action": {
                        "type": "direct_execute",
                        "expected_view": "HistoryCard",
                        "plan": {
                            "plan": [
                                {
                                    "step_id": "s1",
                                    "type": "cli_call",
                                    "cli_group": "deadline",
                                    "cli_command": "transitions",
                                    "args": {"tenant_id": session["tenant_id"], "deadline_id": selected.get("deadline_id")},
                                }
                            ],
                            "intent_label": "deadline_history",
                            "op_class": "read",
                        },
                    },
                }
            )
        spec = get_workspace_spec(workspace_type)
        message = (
            f"这里是{spec.get('purpose', '查阅')}工作区，只用于查看来源和变更记录，不能直接修改截止日。"
            "如果你要改日期，我会先带你回到客户工作区，再走确认流程。"
        )
        return self.response_generator.generate_guidance(
            message,
            [action["label"] for action in actions],
            selectable,
            actions=actions,
            title="先回到可操作的工作区",
            eyebrow="当前页面只支持查阅",
        )

    def _looks_like_due_date_edit(self, user_input: str) -> bool:
        text = user_input.strip().casefold()
        if not text:
            return False
        direct_terms = [
            "改日期",
            "修改日期",
            "改截止",
            "修改截止",
            "改ddl",
            "改 ddl",
            "换日期",
            "调整日期",
            "更新日期",
            "change due date",
            "update due date",
            "change date",
            "override due",
        ]
        if any(term in text for term in direct_terms):
            return True
        edit_terms = ["改", "修改", "调整", "更新", "换", "change", "update", "override"]
        date_terms = ["日期", "截止", "ddl", "due date", "deadline"]
        return any(term in text for term in edit_terms) and any(term in text for term in date_terms)

    def _answer_from_agent_decision(
        self,
        decision: AgentKernelDecision,
        user_input: str,
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        if getattr(decision, "route", None) == "prepare_action":
            return None
        if decision.render_policy in {"render_new_view", "update_current_view"}:
            return self._render_agent_strategy_response(decision, user_input, session)

        if decision.render_policy not in {"keep_current_view", "no_view_needed"}:
            return None
        if decision.need_type not in {"explain_current_view", "answer_advice", "ask_clarifying_question"}:
            return None

        current_view = session.get("current_view")
        if decision.render_policy == "keep_current_view" and (not isinstance(current_view, dict) or not current_view.get("type")):
            return None

        message = decision.answer or self._context_answer_message(user_input, session)
        if decision.next_step and decision.next_step not in message:
            message = f"{message} {decision.next_step}"

        if decision.render_policy == "keep_current_view":
            view = current_view
        elif decision.render_policy == "no_view_needed":
            view = None
        else:
            view = self.response_generator.generate_guidance(message, [])["view"]
        return {
            "message": message,
            "view": view,
            "actions": session.get("current_actions", []),
            "state_summary": session.get("state_summary"),
            "secretary": decision.secretary_envelope,
        }

    def _render_agent_strategy_response(
        self,
        decision: AgentKernelDecision,
        user_input: str,
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        response = self.surface_composer.compose_agent_strategy(decision, user_input, session)
        if response and decision.secretary_envelope:
            response["secretary"] = decision.secretary_envelope
        return response

    def _compose_work_surface_response(
        self,
        plan: WorkSurfacePlan,
        session: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        if plan.surface_plan.surface_kind == "TaxChangeRadar":
            return self._compose_tax_change_radar(plan, session, user_input)
        return self._compose_planned_render_spec(plan, session, user_input)

    def _compose_tax_change_radar(
        self,
        plan: WorkSurfacePlan,
        session: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        evidence = plan.evidence
        clients = evidence.get("clients", [])
        client_names = {client.get("client_id"): client.get("name") for client in clients if client.get("client_id")}
        rules = evidence.get("rules", [])
        review_queue = evidence.get("review_queue", [])
        notices = evidence.get("notices", [])
        deadlines = sorted(
            evidence.get("deadlines", []),
            key=lambda item: (item.get("due_date") or "", item.get("client_id") or ""),
        )
        affected_client_ids = {item.get("client_id") for item in deadlines if item.get("client_id")}
        source_rows: list[dict[str, str]] = []
        for rule in rules[:4]:
            source_rows.append(
                {
                    "label": f"{rule.get('jurisdiction') or '未知辖区'} · {rule.get('tax_type') or '规则'}",
                    "detail": f"当前截止日 {rule.get('deadline_date') or '未知'}，来源 {rule.get('source_url') or '未记录'}",
                }
            )
        for review in review_queue[:3]:
            source_rows.append(
                {
                    "label": f"待审核规则 {review.get('review_id') or ''}".strip(),
                    "detail": f"置信度 {review.get('confidence_score', '未知')}，来源 {review.get('source_url') or '未记录'}",
                }
            )
        for notice in notices[:3]:
            source_rows.append(
                {
                    "label": notice.get("title") or notice.get("notice_id") or "notice",
                    "detail": f"{notice.get('summary') or '无摘要'} 来源 {notice.get('source_url') or '未记录'}",
                }
            )
        if not source_rows:
            source_rows.append(
                {
                    "label": "内部规则库暂无新增信号",
                    "detail": "没有发现规则审核项或 notice 记录；这不代表外部没有税务新闻。",
                }
            )

        impacted_rows = [
            {
                "label": client_names.get(item.get("client_id")) or item.get("client_id") or f"客户 {index}",
                "detail": f"{item.get('tax_type') or 'deadline'} / {item.get('jurisdiction') or '未知辖区'}，截止日 {item.get('due_date') or '未知'}，状态 {item.get('status') or 'unknown'}",
            }
            for index, item in enumerate(deadlines[:6], start=1)
        ]
        if not impacted_rows:
            impacted_rows.append({"label": "暂无近期待处理事项", "detail": "内部数据里没有可关联到客户的 pending deadline。"})

        choices = [
            {"label": button.label, "intent": button.prompt or button.label, "style": "primary" if index == 0 else "secondary"}
            for index, button in enumerate(plan.surface_plan.action_contract)
        ]
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "surface_kind": plan.surface_plan.surface_kind,
            "title": plan.surface_plan.title,
            "intent_summary": plan.surface_plan.primary_question,
            "data_boundary_notice": plan.surface_plan.data_boundary_notice,
            "blocks": [
                {
                    "type": "decision_brief",
                    "title": "先说明边界",
                    "body": plan.surface_plan.data_boundary_notice or "基于当前可用数据判断。",
                },
                {
                    "type": "fact_strip",
                    "facts": [
                        {"label": "规则信号", "value": f"{len(rules)} 条", "tone": "blue"},
                        {"label": "待审核", "value": f"{len(review_queue)} 条", "tone": "gold"},
                        {"label": "可能影响", "value": f"{len(affected_client_ids)} 个客户", "tone": "red" if affected_client_ids else "green"},
                    ],
                },
                {"type": "source_list", "sources": source_rows},
                {"type": "source_list", "sources": impacted_rows},
                {
                    "type": "choice_set",
                    "question": "接下来要看哪一块？",
                    "choices": choices or [{"label": "回到今日清单", "intent": "查看今天的待处理事项", "style": "secondary"}],
                },
            ],
        }
        message = (
            f"我先按秘书助手的方式理解：你要知道有没有影响客户工作的税务变化。"
            f"当前我能查到内部规则库 {len(rules)} 条、待审核规则 {len(review_queue)} 条、notice {len(notices)} 条，"
            f"关联到 {len(affected_client_ids)} 个有近期 pending deadline 的客户。"
            f"注意：当前没有实时外部税务新闻源。"
        )
        return {
            "message": self._truncate_message(message),
            "view": {
                "type": "RenderSpecSurface",
                "data": {"render_spec": render_spec},
                "selectable_items": [
                    self.response_generator._to_selectable(index, item)
                    for index, item in enumerate(deadlines[:10], start=1)
                    if item.get("deadline_id") and item.get("client_id")
                ],
            },
            "actions": [],
            "state_summary": f"{plan.surface_plan.surface_kind}: {plan.need.goal}",
        }

    def _compose_planned_render_spec(
        self,
        plan: WorkSurfacePlan,
        session: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "surface_kind": plan.surface_plan.surface_kind,
            "title": plan.surface_plan.title,
            "intent_summary": plan.surface_plan.primary_question,
            "data_boundary_notice": plan.surface_plan.data_boundary_notice,
            "blocks": [
                {
                    "type": "decision_brief",
                    "title": "结论",
                    "body": plan.need.goal,
                },
                {
                    "type": "choice_set",
                    "question": "下一步怎么推进？",
                    "choices": [
                        {"label": button.label, "intent": button.prompt or button.label, "style": "secondary"}
                        for button in plan.surface_plan.action_contract
                    ],
                },
            ],
        }
        return {
            "message": self._truncate_message(plan.need.goal),
            "view": {"type": "RenderSpecSurface", "data": {"render_spec": render_spec}, "selectable_items": []},
            "actions": [],
            "state_summary": f"{plan.surface_plan.surface_kind}: {plan.need.goal}",
        }

    def _truncate_message(self, message: str, limit: int = 360) -> str:
        return message if len(message) <= limit else message[: limit - 1] + "…"

    def _visible_deadline_items(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        view = session.get("current_view")
        if not isinstance(view, dict):
            return []
        data = view.get("data") if isinstance(view.get("data"), dict) else {}
        raw_items = data.get("items") if isinstance(data.get("items"), list) else data.get("deadlines")
        if not isinstance(raw_items, list):
            return []
        items: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict) or not item.get("deadline_id"):
                continue
            payload = dict(item)
            if "days_remaining" not in payload:
                payload = self.response_generator._enrich_deadline_item(payload, session)
            items.append(payload)
        return items

    def _generic_agent_strategy_response(
        self,
        decision: AgentKernelDecision,
        user_input: str,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        gathered = self._gather_agent_data(decision, session)
        facts = self._agent_fact_strip(gathered)
        sources = self._agent_source_list(gathered)
        title = self._strategy_title(decision)
        body = self._strategy_body(decision, gathered)
        message = decision.answer or self._strategy_message(decision, gathered)
        choices = self._strategy_choices(decision)
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "title": title,
            "intent_summary": user_input,
            "blocks": [
                {
                    "type": "decision_brief",
                    "title": "结论",
                    "body": body,
                },
                {"type": "fact_strip", "facts": facts},
                {"type": "source_list", "sources": sources},
                {
                    "type": "choice_set",
                    "question": "下一步怎么推进？",
                    "choices": choices,
                },
            ],
        }
        selectable = gathered.get("selectable_items", [])
        return {
            "message": message,
            "view": {
                "type": "RenderSpecSurface",
                "data": {"render_spec": render_spec},
                "selectable_items": selectable,
            },
            "actions": [],
            "state_summary": f"Agent strategy surface: {decision.need_type}",
        }

    def _gather_agent_data(
        self,
        decision: AgentKernelDecision,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        tenant_id = session["tenant_id"]
        requests = self._agent_data_requests(decision, session)
        gathered: dict[str, Any] = {
            "current_view": session.get("current_view"),
            "visible_deadlines": [],
            "all_deadlines": [],
            "all_clients": [],
            "client_deadlines": [],
            "selectable_items": [],
        }
        if "current_view" in requests:
            gathered["current_view"] = session.get("current_view")
        if "visible_deadlines" in requests:
            gathered["visible_deadlines"] = self._visible_deadline_items(session)
        if "all_clients" in requests:
            gathered["all_clients"] = [
                self.response_generator._serialize_client(client)
                for client in self.response_generator.engine.list_clients(tenant_id)
            ]
        if "all_deadlines" in requests:
            gathered["all_deadlines"] = [
                self.response_generator._enrich_deadline_item(deadline, session)
                for deadline in self.response_generator.engine.list_deadlines(tenant_id, status=DeadlineStatus.PENDING, limit=200)
            ]
        if "client_deadlines" in requests:
            client_id = self._selected_client_id(session)
            if client_id:
                gathered["client_deadlines"] = [
                    self.response_generator._enrich_deadline_item(deadline, session)
                    for deadline in self.response_generator.engine.list_deadlines(tenant_id, client_id=client_id, status=DeadlineStatus.PENDING, limit=100)
                ]

        deadline_pool = (
            gathered["visible_deadlines"]
            or gathered["client_deadlines"]
            or gathered["all_deadlines"]
        )
        deadline_pool.sort(key=lambda item: (item.get("days_remaining", 9999), item.get("due_date") or "", item.get("client_name") or ""))
        gathered["deadline_pool"] = deadline_pool
        gathered["selectable_items"] = [
            self.response_generator._to_selectable(index, item)
            for index, item in enumerate(deadline_pool[:10], start=1)
            if item.get("deadline_id") and item.get("client_id")
        ]
        return gathered

    def _agent_data_requests(self, decision: AgentKernelDecision, session: dict[str, Any]) -> set[str]:
        requests = set(decision.data_requests or [])
        semantic_text = " ".join(
            str(value or "")
            for value in [
                decision.need_type,
                decision.view_goal,
                decision.answer,
                (session.get("history_window") or [{}])[-1].get("text") if session.get("history_window") else "",
            ]
        ).casefold()
        portfolio_terms = [
            "所有",
            "全部",
            "客户",
            "比较",
            "优先",
            "紧急",
            "不紧急",
            "风险",
            "整体",
            "portfolio",
            "client",
            "compare",
            "priority",
            "urgent",
            "least urgent",
            "risk",
        ]
        if any(term in semantic_text for term in portfolio_terms):
            requests.update({"all_clients", "all_deadlines"})
        if any(term in semantic_text for term in ["这个客户", "当前客户", "client_work", "selected client"]):
            requests.add("client_deadlines")
        if not requests:
            requests.add("current_view")
        return requests

    def _selected_client_id(self, session: dict[str, Any]) -> str | None:
        view = session.get("current_view")
        if isinstance(view, dict):
            data = view.get("data")
            if isinstance(data, dict) and data.get("client_id"):
                return str(data["client_id"])
        selectable = session.get("selectable_items") or []
        if selectable and isinstance(selectable[0], dict) and selectable[0].get("client_id"):
            return str(selectable[0]["client_id"])
        return None

    def _agent_fact_strip(self, gathered: dict[str, Any]) -> list[dict[str, str]]:
        deadlines = gathered.get("deadline_pool", [])
        clients = gathered.get("all_clients", [])
        unique_clients = {item.get("client_id") for item in deadlines if item.get("client_id")}
        next_due = deadlines[0].get("due_date") if deadlines else None
        return [
            {"label": "比较对象", "value": f"{len(unique_clients or clients)} 个客户", "tone": "blue"},
            {"label": "待处理事项", "value": f"{len(deadlines)} 条" if deadlines else "无待处理", "tone": "gold"},
            {"label": "最近截止", "value": str(next_due or "无"), "tone": "red" if next_due else "green"},
        ]

    def _agent_source_list(self, gathered: dict[str, Any]) -> list[dict[str, str]]:
        deadlines = gathered.get("deadline_pool", [])
        if deadlines:
            return [
                {
                    "label": f"{index}. {item.get('client_name') or '当前客户'}",
                    "detail": (
                        f"{item.get('tax_type') or 'deadline'} / {item.get('jurisdiction') or '未知辖区'}，"
                        f"截止日 {item.get('due_date') or '未知'}，状态 {item.get('status') or 'unknown'}"
                    ),
                }
                for index, item in enumerate(deadlines[:6], start=1)
            ]
        clients = gathered.get("all_clients", [])
        if clients:
            return [
                {
                    "label": client.get("name") or f"客户 {index}",
                    "detail": f"{client.get('entity_type') or 'entity'}，{', '.join(client.get('registered_states') or []) or '无州信息'}",
                }
                for index, client in enumerate(clients[:6], start=1)
            ]
        return [{"label": "当前页面", "detail": "基于当前页面给出判断；需要更细的依据时，可以继续追问。"}]

    def _strategy_title(self, decision: AgentKernelDecision) -> str:
        goal = (decision.view_goal or decision.need_type or "工作面").strip()
        if len(goal) <= 18:
            return goal
        return "按需工作面"

    def _strategy_body(self, decision: AgentKernelDecision, gathered: dict[str, Any]) -> str:
        if decision.answer:
            return decision.answer
        goal = decision.view_goal or "判断下一步"
        deadline_count = len(gathered.get("deadline_pool", []))
        client_count = len(gathered.get("all_clients", []))
        if deadline_count:
            return f"我按“{goal}”整理了 {deadline_count} 条待处理事项，下面是判断依据和可继续推进的动作。"
        if client_count:
            return f"我按“{goal}”整理了 {client_count} 个客户，下面先给出可判断的客户范围。"
        return f"我按“{goal}”整理了当前信息；这一步只帮助判断，不会写入任何记录。"

    def _strategy_message(self, decision: AgentKernelDecision, gathered: dict[str, Any]) -> str:
        deadlines = gathered.get("deadline_pool", [])
        if deadlines:
            first = deadlines[0]
            return (
                f"我按“{decision.view_goal or decision.need_type}”整理了当前信息。"
                f"最需要注意的是 {first.get('client_name')} 的 {first.get('tax_type')}，截止日 {first.get('due_date')}。"
            )
        clients = gathered.get("all_clients", [])
        if clients:
            return f"我按“{decision.view_goal or decision.need_type}”整理了 {len(clients)} 个客户的信息。"
        return f"我把这个需求整理成了一个工作面：{decision.view_goal or decision.need_type}。"

    def _strategy_choices(self, decision: AgentKernelDecision) -> list[dict[str, str]]:
        actions = decision.suggested_actions or []
        if actions:
            return actions[:3]
        if decision.next_step:
            return [{"label": decision.next_step[:48], "intent": decision.next_step, "style": "primary"}]
        return [{"label": "回到今日清单", "intent": "查看今天的待处理事项", "style": "secondary"}]

    def _remember_response(self, session: dict[str, Any], response: dict[str, Any]) -> None:
        remember_response_state(session, response)

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
        plan_source_value = plan_source or route.get("source")
        view_type = (response.get("view") or {}).get("type")
        operation = record_operation(
            session,
            user_input=user_input,
            intent_label=plan.get("intent_label"),
            op_class=plan.get("op_class"),
            plan_source=plan_source_value,
            view_type=view_type,
        )
        session["last_turn"] = {
            "user_input": user_input,
            "intent_label": plan.get("intent_label"),
            "op_class": plan.get("op_class"),
            "plan_source": plan_source_value,
            "template_id": route.get("template_id"),
            "similarity": route.get("similarity"),
            "view_type": view_type,
            "workspace_ref": operation.get("workspace_ref"),
            "operation_ref": operation.get("operation_id"),
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

    def _answer_current_context_question(self, user_input: str, session: dict[str, Any]) -> dict[str, Any] | None:
        if not self._looks_like_context_question(user_input):
            return None
        view = session.get("current_view")
        if not isinstance(view, dict) or not view.get("type"):
            return None

        message = self._context_answer_message(user_input, session)
        if not message:
            return None
        return {
            "message": message,
            "view": view,
            "actions": session.get("current_actions", []),
            "state_summary": session.get("state_summary"),
        }

    def _context_answer_message(self, user_input: str, session: dict[str, Any]) -> str | None:
        view = session.get("current_view")
        if not isinstance(view, dict) or not view.get("type"):
            return None
        view_type = view.get("type")
        data = view.get("data") if isinstance(view.get("data"), dict) else {}
        if view_type == "ClientCard":
            return self._answer_client_context_question(user_input, data, session)
        if view_type == "ListCard":
            return self._answer_list_context_question(user_input, data)
        if view_type == "HistoryCard":
            return self._answer_history_context_question(data)
        if view_type == "RenderSpecSurface":
            return self._answer_render_spec_context_question(data)
        return None

    def _looks_like_context_question(self, user_input: str) -> bool:
        text = user_input.strip().casefold()
        if not text:
            return False
        command_terms = [
            "打开",
            "切到",
            "转到",
            "回到",
            "返回",
            "标记",
            "完成",
            "确认",
            "取消",
            "起草",
            "生成",
            "发送",
            "show source",
            "back",
            "go to",
            "open ",
            "focus ",
            "mark ",
            "complete",
            "confirm",
            "cancel",
            "draft",
            "prepare",
        ]
        if any(term in text for term in command_terms):
            return False
        broad_list_terms = ["今天", "today", "列表", "待处理", "todo", "queue"]
        explain_terms = ["分别", "哪些", "是什么", "解释", "说明", "说一下", "list them", "what are", "explain"]
        if any(term in text for term in broad_list_terms) and not any(term in text for term in explain_terms):
            return False
        source_terms = ["来源", "变更", "变了", "为什么变", "谁改", "谁更新", "历史", "source", "history", "changed", "change record"]
        if any(term in text for term in source_terms):
            return False
        question_terms = [
            "?",
            "？",
            "吗",
            "么",
            "什么情况",
            "怎么",
            "为什么",
            "要不要",
            "急",
            "重要",
            "风险",
            "优先",
            "下一步",
            "该干嘛",
            "怎么办",
            "what",
            "why",
            "how",
            "should",
            "urgent",
            "risk",
            "important",
            "next",
        ]
        return any(term in text for term in question_terms)

    def _answer_client_context_question(self, user_input: str, data: dict[str, Any], session: dict[str, Any]) -> str:
        client_name = data.get("client_name") or "这个客户"
        deadlines = [item for item in data.get("deadlines", []) if isinstance(item, dict)]
        if not deadlines:
            return f"{client_name} 当前没有可见的截止事项。右侧我会先保留这个客户页，你可以继续问来源、风险或下一步。"

        sorted_deadlines = sorted(deadlines, key=lambda item: (item.get("due_date") or "", item.get("deadline_id") or ""))
        first = sorted_deadlines[0]
        due_date = first.get("due_date") or "未知日期"
        status = first.get("status") or "unknown"
        tax_type = first.get("tax_type") or "当前事项"
        days_remaining = first.get("days_remaining")
        urgency = "需要优先处理"
        if isinstance(days_remaining, int):
            if days_remaining < 0:
                urgency = "已经逾期，应该优先处理"
            elif days_remaining == 0:
                urgency = "今天到期，应该现在处理"
            elif days_remaining <= 3:
                urgency = "很近了，建议排在前面处理"
            else:
                urgency = "不是最紧急，但需要排进本周队列"

        if self._asks_for_next_step(user_input):
            next_action = "先处理最早到期的一条；如果已经完成，就点击“标记完成”，如果暂时做不了，就选择稍后提醒或标记不适用。"
        elif self._asks_for_urgency(user_input):
            next_action = f"判断依据是最早一条 {tax_type} 在 {due_date}，状态是 {status}。"
        else:
            next_action = f"右侧列出了这个客户的 {len(sorted_deadlines)} 个截止事项，你可以继续问哪条最急、为什么、或直接执行一个动作。"

        return f"{client_name} {urgency}。最早事项是 {tax_type}，截止日 {due_date}，当前状态 {status}。{next_action}"

    def _answer_list_context_question(self, user_input: str, data: dict[str, Any]) -> str:
        items = [item for item in data.get("items", []) if isinstance(item, dict)]
        if not items:
            return "当前列表里没有可见事项。右侧我会保留列表页；你可以换一个范围，比如未来 30 天或某个客户。"
        sorted_items = sorted(items, key=lambda item: (item.get("days_remaining", 9999), item.get("due_date") or ""))
        if self._asks_to_explain_list(user_input):
            rows = []
            for index, item in enumerate(sorted_items, start=1):
                client_name = item.get("client_name") or f"第 {index} 项"
                tax_type = item.get("tax_type") or "未命名事项"
                jurisdiction = item.get("jurisdiction") or "未知辖区"
                due_date = item.get("due_date") or "未知日期"
                status = item.get("status") or "unknown"
                rows.append(f"{index}. {client_name}：{tax_type} / {jurisdiction}，截止日 {due_date}，状态 {status}")
            return f"这页右侧已经是对应的列表工作面，所以我先不换页面。当前可见 {len(sorted_items)} 件事分别是：" + "；".join(rows) + "。要处理某一项，可以直接点那一行，或说“打开第 N 条”。"
        first = sorted_items[0]
        client_name = first.get("client_name") or "第一项"
        tax_type = first.get("tax_type") or "当前事项"
        due_date = first.get("due_date") or "未知日期"
        status = first.get("status") or "unknown"
        if self._asks_for_next_step(user_input) or self._asks_for_urgency(user_input):
            return f"先看 {client_name}。它的 {tax_type} 最靠前，截止日 {due_date}，状态 {status}。右侧列表先保留，方便你打开它或比较其他事项。"
        return f"这个列表当前有 {len(items)} 件事。最值得先看的是 {client_name} 的 {tax_type}，截止日 {due_date}，状态 {status}。"

    def _answer_history_context_question(self, data: dict[str, Any]) -> str:
        client_name = data.get("client_name") or "当前事项"
        source = data.get("source_url") or "当前记录来源"
        transition_count = len(data.get("transitions", []) or [])
        return f"{client_name} 这页是在解释来源和变更记录。当前来源是 {source}，可见变更记录 {transition_count} 条。右侧我会继续保留来源页，方便你核对。"

    def _answer_render_spec_context_question(self, data: dict[str, Any]) -> str:
        spec = data.get("render_spec") if isinstance(data.get("render_spec"), dict) else {}
        title = spec.get("title") or "这个工作面"
        summary = spec.get("intent_summary") or "当前需求"
        return f"{title} 是根据“{summary}”生成的临时工作面。你可以先看右侧建议动作；如果不对，直接告诉我你想改成什么。"

    def _asks_for_urgency(self, user_input: str) -> bool:
        text = user_input.casefold()
        return any(term in text for term in ["急", "重要", "优先", "风险", "urgent", "important", "priority", "risk"])

    def _asks_for_next_step(self, user_input: str) -> bool:
        text = user_input.casefold()
        return any(term in text for term in ["下一步", "怎么办", "该干嘛", "要不要", "next", "should", "what now"])

    def _asks_to_explain_list(self, user_input: str) -> bool:
        text = user_input.casefold()
        return any(
            term in text
            for term in [
                "分别",
                "哪些",
                "是什么",
                "解释",
                "说明",
                "说一下",
                "list them",
                "what are",
                "explain",
            ]
        )
