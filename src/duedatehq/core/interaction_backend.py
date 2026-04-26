from __future__ import annotations

import re
from typing import Any, Protocol

from .agent_kernel import AgentKernel, AgentKernelDecision
from .executor import EntityNotFoundError, PlanExecutionError, PlanExecutor
from .followup_feedback import classify_followup
from .intent_cache import InMemoryIntentLibrary
from .models import DeadlineStatus
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
        agent_kernel: AgentKernel | None = None,
    ) -> None:
        self.executor = executor
        self.response_generator = response_generator
        self.intent_planner = intent_planner
        self.intent_library = intent_library
        self.agent_kernel = agent_kernel

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

        known_plan = self._known_route_plan(text, session)
        if known_plan:
            return self._process_plan_turn(text, known_plan, session, plan_source="known_route")

        kernel_decision = self.agent_kernel.decide(text, session) if self.agent_kernel else None
        kernel_response = self._answer_from_agent_decision(kernel_decision, text, session) if kernel_decision else None
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

        advice_response = self._answer_current_context_question(text, session)
        if advice_response:
            plan = {
                "intent_label": "context_advice",
                "op_class": "read",
            }
            self._remember_response(session, advice_response)
            self._remember_last_turn(
                session,
                text,
                plan,
                advice_response,
                plan_source="context_answer",
            )
            self._append_history(session, "system", advice_response.get("message", ""))
            return {"status": "ok", **advice_response, "session_id": session.get("session_id")}

        plan = self.intent_planner.plan(text, session)
        return self._process_plan_turn(text, plan, session)

    def _process_plan_turn(
        self,
        text: str,
        plan: dict[str, Any],
        session: dict[str, Any],
        *,
        plan_source: str | None = None,
    ) -> dict[str, Any]:
        response = self.process_plan(plan, session)
        if response.get("view", {}).get("type") == "ConfirmCard":
            options = response["view"]["data"].get("options", [])
            primary = next((option for option in options if option.get("plan")), None)
            if primary:
                session["pending_action_plan"] = primary["plan"]

        self._remember_response(session, response)
        self._remember_last_turn(session, text, plan, response, plan_source=plan_source)
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

    def _known_route_plan(self, user_input: str, session: dict[str, Any]) -> dict[str, Any] | None:
        """Resolve deterministic UI routes before the open-ended Agent Kernel.

        Existing work-surface actions such as "打开第 1 条" are not semantic
        long-tail requests. They should hit the known view contract first so a
        row click opens the cached ClientCard path instead of asking Claude to
        synthesize a temporary surface.
        """
        return self._relative_visible_item_plan(user_input, session)

    def _relative_visible_item_plan(self, user_input: str, session: dict[str, Any]) -> dict[str, Any] | None:
        lowered = user_input.casefold()
        if not any(token in lowered for token in ["打开", "查看", "看", "focus", "open", "show"]):
            return None
        selectable = session.get("selectable_items") or []
        if not selectable:
            return None
        match = re.search(r"(?:第\s*)?([1-9])\s*(?:条|个|项|item)", lowered)
        if not match:
            match = re.search(r"item\s*([1-9])", lowered)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(selectable):
                item = selectable[index]
                return self._client_deadline_plan(session["tenant_id"], item["client_id"])
            return None
        if any(token in lowered for token in ["第一", "第一个", "first", "1st"]):
            return self._client_deadline_plan(session["tenant_id"], selectable[0]["client_id"])
        if any(token in lowered for token in ["第二", "second", "2nd"]) and len(selectable) > 1:
            return self._client_deadline_plan(session["tenant_id"], selectable[1]["client_id"])
        if any(token in lowered for token in ["第三", "third", "3rd"]) and len(selectable) > 2:
            return self._client_deadline_plan(session["tenant_id"], selectable[2]["client_id"])
        return None

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

    def _answer_from_agent_decision(
        self,
        decision: AgentKernelDecision,
        user_input: str,
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        if getattr(decision, "route", None) == "pass_to_planner":
            return None
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
        else:
            view = self.response_generator.generate_guidance(message, [])["view"]
        return {
            "message": message,
            "view": view,
            "actions": session.get("current_actions", []),
            "state_summary": session.get("state_summary"),
        }

    def _render_agent_strategy_response(
        self,
        decision: AgentKernelDecision,
        user_input: str,
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not session.get("tenant_id"):
            return None
        return self._generic_agent_strategy_response(decision, user_input, session)

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
                    "title": "我先把需求收敛成工作面",
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
        requests = set(decision.data_requests or [])
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
        overdue = [item for item in deadlines if item.get("days_remaining", 0) < 0]
        next_due = deadlines[0].get("due_date") if deadlines else "无"
        return [
            {"label": "客户", "value": str(len(clients)) if clients else "当前范围", "tone": "blue"},
            {"label": "待处理", "value": str(len(deadlines)), "tone": "gold"},
            {"label": "最早截止", "value": str(next_due), "tone": "red" if overdue else "green"},
        ]

    def _agent_source_list(self, gathered: dict[str, Any]) -> list[dict[str, str]]:
        deadlines = gathered.get("deadline_pool", [])
        if deadlines:
            return [
                {
                    "label": item.get("client_name") or f"事项 {index}",
                    "detail": (
                        f"{item.get('tax_type') or 'deadline'} / {item.get('jurisdiction') or '未知辖区'}，"
                        f"{item.get('due_date') or '未知日期'}，{item.get('status') or 'unknown'}"
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
        return [{"label": "当前页面", "detail": "这次需求没有读取到额外数据，右侧保留为决策工作面。"}]

    def _strategy_title(self, decision: AgentKernelDecision) -> str:
        goal = (decision.view_goal or decision.need_type or "工作面").strip()
        if len(goal) <= 18:
            return goal
        return "按需工作面"

    def _strategy_body(self, decision: AgentKernelDecision, gathered: dict[str, Any]) -> str:
        requests = "、".join(decision.data_requests or ["current_view"])
        goal = decision.view_goal or "帮助你判断下一步"
        deadline_count = len(gathered.get("deadline_pool", []))
        client_count = len(gathered.get("all_clients", []))
        return (
            f"我把这句话理解为：{goal}。"
            f"本轮只读取允许的数据：{requests}。"
            f"当前工作面汇总了 {client_count if client_count else '当前范围内'} 个客户和 {deadline_count} 个待处理事项；不会写入任何记录。"
        )

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
        view = response.get("view") or {}
        session["current_view"] = view
        session["selectable_items"] = view.get("selectable_items", [])
        session["current_actions"] = response.get("actions", [])
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
