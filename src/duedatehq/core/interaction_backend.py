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
from .work_surface_planner import WorkSurfacePlan, WorkSurfacePlanner
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
        self.work_surface_planner = WorkSurfacePlanner(response_generator.engine)
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
            self._append_history(session, "system", response.get("message", "Handled."))
            return response

        if self.intent_planner.is_cancel(text) and pending_action:
            session.pop("pending_action_plan", None)
            response = self.response_generator.generate_guidance(
                "Canceled. The current task was not changed.",
                ["View today's queue", "Continue with current client"],
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

        tax_change_surface_plan = self._tax_change_surface_plan(text, session)
        if tax_change_surface_plan:
            response = self.surface_composer.compose_work_surface(tax_change_surface_plan, session, text)
            self._remember_response(session, response)
            self._remember_last_turn(
                session,
                text,
                {"intent_label": tax_change_surface_plan.surface_plan.surface_kind, "op_class": "read"},
                response,
                plan_source="tax_change_forced_route",
            )
            self._append_history(session, "system", response.get("message", ""))
            return {"status": "ok", **response, "session_id": session.get("session_id")}

        confirmation_plan = self._short_confirmation_plan(text, session)
        if confirmation_plan:
            return self._process_plan_turn(text, confirmation_plan, session, plan_source="secretary_confirmation")

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

        known_plan = self._known_route_plan(text, session)
        if known_plan:
            return self._process_plan_turn(text, known_plan, session, plan_source="known_route")

        work_surface_plan = self.work_surface_planner.plan(text, session)
        if work_surface_plan:
            response = self.surface_composer.compose_work_surface(work_surface_plan, session, text)
            self._remember_response(session, response)
            self._remember_last_turn(
                session,
                text,
                {"intent_label": work_surface_plan.surface_plan.surface_kind, "op_class": "read"},
                response,
                plan_source="work_surface_planner_fallback",
            )
            self._append_history(session, "system", response.get("message", ""))
            return {"status": "ok", **response, "session_id": session.get("session_id")}

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
                plan.get("message", "I could not find that record."),
                plan.get("options", []),
                plan.get("selectable_items", []),
            )
        if plan.get("special") == "reopen_unavailable":
            return self.response_generator.generate_guidance(
                plan.get("message", "The current status does not support reopening."),
                ["View today's queue"],
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
                f"I could not find that entity: {exc}",
                ["View today's queue", "Look up a specific client"],
            )
        except PlanExecutionError as exc:
            return self.response_generator.generate_guidance(
                f"Execution failed: {exc}",
                ["View today's queue"],
            )

        return self.response_generator.generate(executor_result, session)

    def process_direct_action(self, plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        return self._process_plan_turn("__direct_action__", plan, session, plan_source="direct_action")

    def process_direct_command(self, command: str, session: dict[str, Any]) -> dict[str, Any]:
        if command == "confirm_pending":
            pending_plan = session.pop("pending_action_plan", None)
            if not pending_plan:
                response = self.response_generator.generate_guidance(
                    "There is no pending confirmation. No data was changed.",
                    ["View today's queue"],
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
            self._append_history(session, "system", response.get("message", "Handled."))
            return response

        if command == "cancel_pending":
            session.pop("pending_action_plan", None)
            response = self.response_generator.generate_guidance(
                "Canceled. The current task was not changed.",
                ["View today's queue", "Continue with current client"],
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
            "This button command is not executable yet. No data was changed.",
            ["View today's queue"],
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

    def _known_route_plan(self, user_input: str, session: dict[str, Any]) -> dict[str, Any] | None:
        """Resolve deterministic UI routes after the Agent Kernel hands off.

        Only object navigation belongs here. Open-ended requests like
        "prepare request" or "draft an email" must stay agent-led because the
        useful surface depends on current context and user intent.
        """
        return self._relative_visible_item_plan(user_input, session)

    def _tax_change_surface_plan(self, user_input: str, session: dict[str, Any]) -> WorkSurfacePlan | None:
        current_view = session.get("current_view")
        if isinstance(current_view, dict) and current_view.get("type") == "TaxChangeRadarCard":
            return None
        plan = self.work_surface_planner.plan(user_input, session)
        if not plan or plan.surface_plan.surface_kind != "TaxChangeRadar":
            return None
        return plan

    def _short_confirmation_plan(self, user_input: str, session: dict[str, Any]) -> dict[str, Any] | None:
        text = user_input.strip().casefold()
        if text not in {"好", "好的", "ok", "okay", "yes", "yep", "do that", "先处理这个", "就这个"}:
            return None
        selectable = session.get("selectable_items") or []
        first = next((item for item in selectable if isinstance(item, dict) and item.get("client_id")), None)
        if not first or not session.get("tenant_id"):
            return None
        return self._client_deadline_plan(session["tenant_id"], str(first["client_id"]))

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
                    "label": "Back to client workspace",
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
                    "label": "Keep reviewing source",
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
            "This page cannot directly modify a deadline. "
            f"It is a {spec.get('purpose', 'read-only')} workspace for reviewing source and change history. "
            "If you want to change a date, I will take you back to the client workspace first, then use the confirmation flow."
        )
        return self.response_generator.generate_guidance(
            message,
            [action["label"] for action in actions],
            selectable,
            actions=actions,
            title="Return to an actionable workspace",
            eyebrow="This page is read-only",
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

        message = self._english_agent_answer(decision) or self._context_answer_message(user_input, session)
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
            "secretary": decision.secretary_envelope,
        }

    def _render_agent_strategy_response(
        self,
        decision: AgentKernelDecision,
        user_input: str,
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        direct_response = self._render_registered_workspace_from_agent(decision, session)
        if direct_response:
            return direct_response
        response = self.surface_composer.compose_agent_strategy(decision, user_input, session)
        if response and decision.secretary_envelope:
            response["secretary"] = decision.secretary_envelope
        return response

    def _render_registered_workspace_from_agent(
        self,
        decision: AgentKernelDecision,
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        envelope = decision.secretary_envelope if isinstance(decision.secretary_envelope, dict) else {}
        action = envelope.get("action") if isinstance(envelope.get("action"), dict) else {}
        template = str(action.get("template") or "").casefold().strip()
        workspace = action.get("workspace") if isinstance(action.get("workspace"), dict) else {}
        fields = workspace.get("fields") if isinstance(workspace.get("fields"), dict) else {}

        if template in {"today", "today_queue", "workload_plan"}:
            response = self.process_plan(
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
                },
                session,
            )
            return self._with_agent_reply(response, decision)

        if template in {"client_summary", "client_workspace", "client", "deadline_view"}:
            client_id = self._client_id_from_agent_fields(fields, session)
            if not client_id:
                return None
            response = self.process_plan(self._client_deadline_plan(session["tenant_id"], client_id), session)
            return self._with_agent_reply(response, decision)

        return None

    def _with_agent_reply(self, response: dict[str, Any], decision: AgentKernelDecision) -> dict[str, Any]:
        if decision.answer:
            response["message"] = decision.answer
        if decision.secretary_envelope:
            response["secretary"] = decision.secretary_envelope
        return response

    def _client_id_from_agent_fields(self, fields: dict[str, Any], session: dict[str, Any]) -> str | None:
        entity = fields.get("entity") if isinstance(fields.get("entity"), dict) else {}
        data = fields.get("data") if isinstance(fields.get("data"), dict) else {}
        candidates: list[Any] = [
            fields.get("client_id"),
            entity.get("value"),
            data.get("value"),
        ]
        for value in candidates:
            client_id = self._client_id_from_value(value, session)
            if client_id:
                return client_id

        for item in session.get("selectable_items") or []:
            if isinstance(item, dict) and item.get("client_id"):
                return str(item["client_id"])
        return None

    def _client_id_from_value(self, value: Any, session: dict[str, Any]) -> str | None:
        if isinstance(value, dict):
            for key in ("client_id", "id"):
                if value.get(key):
                    return str(value[key])
            if value.get("client") and isinstance(value["client"], dict):
                return self._client_id_from_value(value["client"], session)
            if value.get("name"):
                return self._client_id_from_name(str(value["name"]), session)
        if isinstance(value, list):
            for item in value:
                client_id = self._client_id_from_value(item, session)
                if client_id:
                    return client_id
            return None
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if any(isinstance(item, dict) and item.get("client_id") == text for item in session.get("selectable_items") or []):
            return text
        return self._client_id_from_name(text, session)

    def _client_id_from_name(self, name: str, session: dict[str, Any]) -> str | None:
        if not session.get("tenant_id"):
            return None
        needle = name.casefold().strip()
        if not needle:
            return None
        for client in self.response_generator.engine.list_clients(session["tenant_id"]):
            client_name = client.name.casefold()
            if needle == client.client_id.casefold() or needle == client_name or needle in client_name or client_name in needle:
                return client.client_id
        return None

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
                    "label": f"{rule.get('jurisdiction') or 'Unknown jurisdiction'} · {rule.get('tax_type') or 'Rule'}",
                    "detail": f"Current due date {rule.get('deadline_date') or 'unknown'}, source {rule.get('source_url') or 'not recorded'}",
                }
            )
        for review in review_queue[:3]:
            source_rows.append(
                {
                    "label": f"Rule needing review {review.get('review_id') or ''}".strip(),
                    "detail": f"Confidence {review.get('confidence_score', 'unknown')}, source {review.get('source_url') or 'not recorded'}",
                }
            )
        for notice in notices[:3]:
            source_rows.append(
                {
                    "label": notice.get("title") or notice.get("notice_id") or "notice",
                    "detail": f"{notice.get('summary') or 'No summary'} Source {notice.get('source_url') or 'not recorded'}",
                }
            )
        if not source_rows:
            source_rows.append(
                {
                    "label": "No new internal rule signals",
                    "detail": "No rule review items or notice records were found. This does not mean there is no external tax news.",
                }
            )

        impacted_rows = [
            {
                "label": client_names.get(item.get("client_id")) or item.get("client_id") or f"Client {index}",
                "detail": f"{item.get('tax_type') or 'deadline'} / {item.get('jurisdiction') or 'Unknown jurisdiction'}, due {item.get('due_date') or 'unknown'}, status {item.get('status') or 'unknown'}",
            }
            for index, item in enumerate(deadlines[:6], start=1)
        ]
        if not impacted_rows:
            impacted_rows.append({"label": "No upcoming pending items", "detail": "Internal data has no pending deadlines that can be linked to clients."})

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
                    "title": "Data boundary",
                    "body": plan.surface_plan.data_boundary_notice or "I will judge from the currently available data.",
                },
                {
                    "type": "fact_strip",
                    "facts": [
                        {"label": "Rule signals", "value": f"{len(rules)} items", "tone": "blue"},
                        {"label": "Needs review", "value": f"{len(review_queue)} items", "tone": "gold"},
                        {"label": "May affect", "value": f"{len(affected_client_ids)} clients", "tone": "red" if affected_client_ids else "green"},
                    ],
                },
                {"type": "source_list", "sources": source_rows},
                {"type": "source_list", "sources": impacted_rows},
                {
                    "type": "choice_set",
                    "question": "What should we inspect next?",
                    "choices": choices or [{"label": "Back to today's queue", "intent": "View today's queue", "style": "secondary"}],
                },
            ],
        }
        message = (
            f"I understand this as a tax-change monitoring request for client work. "
            f"I can see {len(rules)} internal rules, {len(review_queue)} rules needing review, {len(notices)} notices, "
            f"and {len(affected_client_ids)} clients with upcoming pending deadlines. "
            "No real-time external tax news feed is connected."
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
                    "title": "Conclusion",
                    "body": plan.need.goal,
                },
                {
                    "type": "choice_set",
                    "question": "What should we do next?",
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
        message = self._english_agent_answer(decision) or self._strategy_message(decision, gathered)
        choices = self._strategy_choices(decision)
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "title": title,
            "intent_summary": user_input,
            "blocks": [
                {
                    "type": "decision_brief",
                    "title": "Conclusion",
                    "body": body,
                },
                {"type": "fact_strip", "facts": facts},
                {"type": "source_list", "sources": sources},
                {
                    "type": "choice_set",
                    "question": "What should we do next?",
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
            {"label": "Comparison scope", "value": f"{len(unique_clients or clients)} clients", "tone": "blue"},
            {"label": "Pending items", "value": f"{len(deadlines)} items" if deadlines else "None pending", "tone": "gold"},
            {"label": "Nearest due", "value": str(next_due or "None"), "tone": "red" if next_due else "green"},
        ]

    def _agent_source_list(self, gathered: dict[str, Any]) -> list[dict[str, str]]:
        deadlines = gathered.get("deadline_pool", [])
        if deadlines:
            return [
                {
                    "label": f"{index}. {item.get('client_name') or 'Current client'}",
                    "detail": (
                        f"{item.get('tax_type') or 'deadline'} / {item.get('jurisdiction') or 'Unknown jurisdiction'}, "
                        f"due {item.get('due_date') or 'unknown'}, status {item.get('status') or 'unknown'}"
                    ),
                }
                for index, item in enumerate(deadlines[:6], start=1)
            ]
        clients = gathered.get("all_clients", [])
        if clients:
            return [
                {
                    "label": client.get("name") or f"Client {index}",
                    "detail": f"{client.get('entity_type') or 'entity'}, {', '.join(client.get('registered_states') or []) or 'No state information'}",
                }
                for index, client in enumerate(clients[:6], start=1)
            ]
        return [{"label": "Current page", "detail": "I will base the judgment on the current page first. Ask for more detail if you need supporting evidence."}]

    def _strategy_title(self, decision: AgentKernelDecision) -> str:
        goal = (decision.view_goal or decision.need_type or "Workspace").strip()
        if re.search(r"[\u4e00-\u9fff]", goal):
            return "On-Demand Workspace"
        if len(goal) <= 18:
            return goal
        return "On-Demand Workspace"

    def _strategy_body(self, decision: AgentKernelDecision, gathered: dict[str, Any]) -> str:
        english_answer = self._english_agent_answer(decision)
        if english_answer:
            return english_answer
        goal = self._english_goal(decision)
        deadline_count = len(gathered.get("deadline_pool", []))
        client_count = len(gathered.get("all_clients", []))
        if deadline_count:
            return f"I organized {deadline_count} pending items around '{goal}'. The supporting evidence and next actions are below."
        if client_count:
            return f"I organized {client_count} clients around '{goal}'. The client scope is below."
        return f"I organized the current information around '{goal}'. This helps with judgment only and does not write records."

    def _strategy_message(self, decision: AgentKernelDecision, gathered: dict[str, Any]) -> str:
        deadlines = gathered.get("deadline_pool", [])
        if deadlines:
            first = deadlines[0]
            return (
                f"I organized the current information around '{self._english_goal(decision)}'. "
                f"The item needing the most attention is {first.get('client_name')}'s {first.get('tax_type')}, due {first.get('due_date')}."
            )
        clients = gathered.get("all_clients", [])
        if clients:
            return f"I organized information for {len(clients)} clients around '{self._english_goal(decision)}'."
        return f"I turned this request into a workspace: {self._english_goal(decision)}."

    def _english_goal(self, decision: AgentKernelDecision) -> str:
        goal = str(decision.view_goal or decision.need_type or "Decide the next step").strip()
        if not goal or re.search(r"[\u4e00-\u9fff]", goal):
            return str(decision.need_type or "Decide the next step").replace("_", " ")
        return goal

    def _english_agent_answer(self, decision: AgentKernelDecision) -> str | None:
        answer = str(decision.answer or "").strip()
        if not answer or re.search(r"[\u4e00-\u9fff]", answer):
            return None
        return answer

    def _strategy_choices(self, decision: AgentKernelDecision) -> list[dict[str, str]]:
        actions = decision.suggested_actions or []
        if actions:
            return [self._english_choice(action, index) for index, action in enumerate(actions[:3])]
        if decision.next_step:
            label = decision.next_step[:48]
            if re.search(r"[\u4e00-\u9fff]", label):
                label = "Continue"
            return [{"label": label, "intent": decision.next_step, "style": "primary"}]
        return [{"label": "Back to today's queue", "intent": "View today's queue", "style": "secondary"}]

    def _english_choice(self, action: dict[str, str], index: int) -> dict[str, str]:
        label = str(action.get("label") or "").strip()
        intent = str(action.get("intent") or label or "Continue").strip()
        style = str(action.get("style") or ("primary" if index == 0 else "secondary"))
        if not label or re.search(r"[\u4e00-\u9fff]", label):
            semantic = f"{label} {intent}".casefold()
            label = "Open highest-risk client" if any(term in semantic for term in ["风险最高", "highest-risk", "highest risk"]) else "Continue"
        return {"label": label, "intent": intent, "style": style}

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
        if view_type == "TaxChangeRadarCard":
            return self._answer_tax_change_radar_context_question(user_input, data)
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
            "which",
            "affected",
            "impact",
            "impacted",
            "urgent",
            "risk",
            "important",
            "next",
        ]
        return any(term in text for term in question_terms)

    def _answer_client_context_question(self, user_input: str, data: dict[str, Any], session: dict[str, Any]) -> str:
        client_name = data.get("client_name") or "This client"
        deadlines = [item for item in data.get("deadlines", []) if isinstance(item, dict)]
        if not deadlines:
            return f"{client_name} has no visible deadlines right now. I will keep the client page open so you can ask about source, risk, or next steps."

        sorted_deadlines = sorted(deadlines, key=lambda item: (item.get("due_date") or "", item.get("deadline_id") or ""))
        first = sorted_deadlines[0]
        due_date = first.get("due_date") or "unknown date"
        status = first.get("status") or "unknown"
        tax_type = first.get("tax_type") or "current item"
        days_remaining = first.get("days_remaining")
        urgency = "should be prioritized"
        if isinstance(days_remaining, int):
            if days_remaining < 0:
                urgency = "is overdue and should be prioritized"
            elif days_remaining == 0:
                urgency = "is due today and should be handled now"
            elif days_remaining <= 3:
                urgency = "is close and should stay near the front of the queue"
            else:
                urgency = "is not the most urgent item, but belongs in this week's queue"

        if self._asks_for_next_step(user_input):
            next_action = "Start with the earliest due item. If it is already done, use Mark complete; if it cannot be handled yet, use Remind later or Mark not applicable."
        elif self._asks_for_urgency(user_input):
            next_action = f"The basis is the earliest item: {tax_type}, due {due_date}, with status {status}."
        else:
            next_action = f"The workspace lists {len(sorted_deadlines)} deadlines for this client. You can ask which is most urgent, why it matters, or run an available action."

        return f"{client_name} {urgency}. The earliest item is {tax_type}, due {due_date}, current status {status}. {next_action}"

    def _answer_list_context_question(self, user_input: str, data: dict[str, Any]) -> str:
        items = [item for item in data.get("items", []) if isinstance(item, dict)]
        if not items:
            return "There are no visible items in the current list. I will keep the list open; you can switch scope, such as the next 30 days or one client."
        sorted_items = sorted(items, key=lambda item: (item.get("days_remaining", 9999), item.get("due_date") or ""))
        if self._asks_to_explain_list(user_input):
            rows = []
            for index, item in enumerate(sorted_items, start=1):
                client_name = item.get("client_name") or f"Item {index}"
                tax_type = item.get("tax_type") or "Unnamed item"
                jurisdiction = item.get("jurisdiction") or "Unknown jurisdiction"
                due_date = item.get("due_date") or "unknown date"
                status = item.get("status") or "unknown"
                rows.append(f"{index}. {client_name}: {tax_type} / {jurisdiction}, due {due_date}, status {status}")
            return f"The right side is already the matching list workspace, so I will keep it open. The {len(sorted_items)} visible items are: " + "; ".join(rows) + ". To handle one, click the row or say 'open item N'."
        first = sorted_items[0]
        client_name = first.get("client_name") or "the first item"
        tax_type = first.get("tax_type") or "current item"
        due_date = first.get("due_date") or "unknown date"
        status = first.get("status") or "unknown"
        if self._asks_for_next_step(user_input) or self._asks_for_urgency(user_input):
            return f"Start with {client_name}. Its {tax_type} is earliest, due {due_date}, status {status}. I will keep the list open so you can open it or compare other items."
        return f"This list currently has {len(items)} items. The best first item is {client_name}'s {tax_type}, due {due_date}, status {status}."

    def _answer_history_context_question(self, data: dict[str, Any]) -> str:
        client_name = data.get("client_name") or "The current item"
        source = data.get("source_url") or "the current record source"
        transition_count = len(data.get("transitions", []) or [])
        return f"{client_name} is on the source and change-history page. Current source: {source}. Visible change records: {transition_count}. I will keep this source page open for review."

    def _answer_render_spec_context_question(self, data: dict[str, Any]) -> str:
        spec = data.get("render_spec") if isinstance(data.get("render_spec"), dict) else {}
        title = spec.get("title") or "This workspace"
        summary = spec.get("intent_summary") or "the current request"
        return f"{title} is a temporary workspace generated from '{summary}'. Review the suggested actions on the right; if it is not right, tell me what to change."

    def _answer_tax_change_radar_context_question(self, user_input: str, data: dict[str, Any]) -> str:
        impacted = [item for item in data.get("impacted_deadlines", []) if isinstance(item, dict)]
        signals = [item for item in data.get("rule_signals", []) if isinstance(item, dict)]
        if not impacted:
            return (
                "This change does not currently match any pending deadlines in the visible client set. "
                "I will keep the tax change radar open so you can review the source and rule signals."
            )

        rows = []
        for item in impacted[:6]:
            client_name = item.get("client_name") or "Unknown client"
            tax_type = item.get("tax_type") or "unknown tax type"
            jurisdiction = item.get("jurisdiction") or "unknown jurisdiction"
            due_date = item.get("due_date") or "unknown date"
            status = item.get("status") or "unknown"
            rows.append(f"{client_name}: {tax_type} / {jurisdiction}, due {due_date}, status {status}")

        signal_hint = ""
        if signals:
            first = signals[0]
            title = first.get("title") or "current rule signal"
            source = first.get("source") or "no recorded source"
            signal_hint = f" I matched this against the current rule signal '{title}' from {source}."

        overflow = ""
        if len(impacted) > len(rows):
            overflow = f" I am showing the first {len(rows)} of {len(impacted)} affected items."

        return (
            f"This change currently matches {len(impacted)} affected client items: "
            + "; ".join(rows)
            + f".{signal_hint}{overflow} You can review the details here, then open the client workspace for the affected filing."
        )

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
