from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .agent_kernel import AgentKernelDecision
from .models import DeadlineStatus
from .response_generator import ResponseGenerator
from .work_surface_planner import WorkSurfacePlan


class SurfaceComposer:
    """Build workspace surfaces from agent and planner decisions.

    The interaction backend should decide route order. This composer owns the
    translation from a semantic decision into a concrete view payload.
    """

    def __init__(self, response_generator: ResponseGenerator) -> None:
        self.response_generator = response_generator
        self.engine = response_generator.engine

    def compose_work_surface(
        self,
        plan: WorkSurfacePlan,
        session: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        if plan.surface_plan.surface_kind == "TaxChangeRadar":
            return self._compose_tax_change_radar(plan, session)
        return self._compose_planned_render_spec(plan, user_input)

    def compose_agent_strategy(
        self,
        decision: AgentKernelDecision,
        user_input: str,
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not session.get("tenant_id"):
            return None
        gathered = self._gather_agent_data(decision, session)
        if self._agent_wants_tax_change_radar(decision):
            return self._compose_agent_tax_change_radar(decision, gathered, session)
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
                {"type": "decision_brief", "title": "Conclusion", "body": body},
                {"type": "fact_strip", "facts": facts},
                {"type": "source_list", "sources": sources},
                {"type": "choice_set", "question": "What should we do next?", "choices": choices},
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

    def _agent_wants_tax_change_radar(self, decision: AgentKernelDecision) -> bool:
        semantic_text = " ".join(
            str(value or "")
            for value in [
                getattr(decision, "surface_kind", None),
                decision.need_type,
                decision.view_goal,
                decision.answer,
            ]
        ).casefold()
        return any(
            term in semantic_text
            for term in [
                "taxchangeradar",
                "tax_change",
                "tax change",
                "tax news",
                "policy",
                "notice",
                "rule change",
                "政策",
                "税务",
                "税法",
                "规则",
                "法规",
            ]
        )

    def _compose_agent_tax_change_radar(
        self,
        decision: AgentKernelDecision,
        gathered: dict[str, Any],
        session: dict[str, Any],
    ) -> dict[str, Any]:
        rules = gathered.get("rules", [])
        review_queue = gathered.get("review_queue", [])
        notices = gathered.get("notices", [])
        deadlines = sorted(
            gathered.get("deadline_pool", []),
            key=lambda item: (item.get("due_date") or "", item.get("client_name") or ""),
        )
        affected_client_ids = {item.get("client_id") for item in deadlines if item.get("client_id")}

        rule_signals: list[dict[str, str]] = []
        for rule in rules[:4]:
            rule_signals.append(
                {
                    "title": f"{rule.get('jurisdiction') or 'Unknown jurisdiction'} · {rule.get('tax_type') or 'Rule'}",
                    "detail": f"Current due date {rule.get('deadline_date') or 'unknown'}",
                    "source": rule.get("source_url") or "No source recorded",
                }
            )
        for review in review_queue[:3]:
            rule_signals.append(
                {
                    "title": f"Rule needing review {review.get('review_id') or ''}".strip(),
                    "detail": f"Confidence {review.get('confidence_score', 'unknown')}",
                    "source": review.get("source_url") or "No source recorded",
                }
            )
        for notice in notices[:3]:
            rule_signals.append(
                {
                    "title": notice.get("title") or notice.get("notice_id") or "Notice",
                    "detail": notice.get("summary") or "No summary",
                    "source": notice.get("source_url") or "No source recorded",
                }
            )
        if not rule_signals:
            rule_signals.append(
                {
                    "title": "No new internal rule signals",
                    "detail": "No rule review items or notice records were found. This does not mean there is no external tax news.",
                    "source": "Internal rule library",
                }
            )

        data = {
            "title": "Monthly Tax Change Radar",
            "primary_question": decision.view_goal or "Which policies, rules, or notices may affect current clients?",
            "data_boundary_notice": "No real-time external tax news feed is connected. These results only use the internal rule library, rule review queue, notice records, and client deadlines.",
            "metrics": [
                {"label": "Rule signals", "value": f"{len(rules)} items", "tone": "blue"},
                {"label": "Needs review", "value": f"{len(review_queue)} items", "tone": "gold"},
                {"label": "May affect", "value": f"{len(affected_client_ids)} clients", "tone": "red" if affected_client_ids else "green"},
            ],
            "rule_signals": rule_signals,
            "impacted_deadlines": [
                {
                    "client_name": item.get("client_name") or item.get("client_id") or f"Client {index}",
                    "tax_type": item.get("tax_type") or "deadline",
                    "jurisdiction": item.get("jurisdiction") or "Unknown jurisdiction",
                    "due_date": item.get("due_date") or "unknown",
                    "status": item.get("status") or "unknown",
                    "deadline_id": item.get("deadline_id"),
                    "client_id": item.get("client_id"),
                }
                for index, item in enumerate(deadlines[:8], start=1)
            ],
        }
        message = self._english_agent_answer(decision) or (
            f"I organized the available data as a tax change radar: {len(rules)} internal rules, "
            f"{len(review_queue)} rules needing review, {len(notices)} notices, "
            f"and {len(affected_client_ids)} clients with upcoming pending deadlines. "
            "No real-time external tax news feed is connected."
        )
        return {
            "message": self._truncate_message(message),
            "view": {
                "type": "TaxChangeRadarCard",
                "data": data,
                "selectable_items": gathered.get("selectable_items", []),
            },
            "actions": [
                {
                    "label": "View rule review queue",
                    "action": {
                        "type": "direct_execute",
                        "expected_view": "ReviewQueueCard",
                        "plan": {
                            "plan": [
                                {
                                    "step_id": "s1",
                                    "type": "cli_call",
                                    "cli_group": "rule",
                                    "cli_command": "review-queue",
                                    "args": {},
                                }
                            ],
                            "intent_label": "rule_review",
                            "op_class": "read",
                        },
                    },
                },
                {
                    "label": "View upcoming deadlines",
                    "action": {
                        "type": "direct_execute",
                        "expected_view": "ListCard",
                        "plan": {
                            "plan": [
                                {
                                    "step_id": "s1",
                                    "type": "cli_call",
                                    "cli_group": "deadline",
                                    "cli_command": "list",
                                    "args": {"tenant_id": session.get("tenant_id"), "within_days": 30, "status": "pending"},
                                }
                            ],
                            "intent_label": "upcoming_deadlines",
                            "op_class": "read",
                        },
                    },
                },
            ],
            "state_summary": f"TaxChangeRadar: {decision.need_type}",
        }

    def _compose_tax_change_radar(
        self,
        plan: WorkSurfacePlan,
        session: dict[str, Any],
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

        rule_signals: list[dict[str, str]] = []
        for rule in rules[:4]:
            rule_signals.append(
                {
                    "title": f"{rule.get('jurisdiction') or 'Unknown jurisdiction'} · {rule.get('tax_type') or 'Rule'}",
                    "detail": f"Current due date {rule.get('deadline_date') or 'unknown'}",
                    "source": rule.get("source_url") or "No source recorded",
                }
            )
        for review in review_queue[:3]:
            rule_signals.append(
                {
                    "title": f"Rule needing review {review.get('review_id') or ''}".strip(),
                    "detail": f"Confidence {review.get('confidence_score', 'unknown')}",
                    "source": review.get("source_url") or "No source recorded",
                }
            )
        for notice in notices[:3]:
            rule_signals.append(
                {
                    "title": notice.get("title") or notice.get("notice_id") or "Notice",
                    "detail": notice.get("summary") or "No summary",
                    "source": notice.get("source_url") or "No source recorded",
                }
            )
        if not rule_signals:
            rule_signals.append(
                {
                    "title": "No new internal rule signals",
                    "detail": "No rule review items or notice records were found. This does not mean there is no external tax news.",
                    "source": "Internal rule library",
                }
            )

        impacted_deadlines = [
            {
                "client_name": client_names.get(item.get("client_id")) or item.get("client_id") or f"Client {index}",
                "tax_type": item.get("tax_type") or "deadline",
                "jurisdiction": item.get("jurisdiction") or "Unknown jurisdiction",
                "due_date": item.get("due_date") or "unknown",
                "status": item.get("status") or "unknown",
                "deadline_id": item.get("deadline_id"),
                "client_id": item.get("client_id"),
            }
            for index, item in enumerate(deadlines[:8], start=1)
        ]

        data = {
            "title": plan.surface_plan.title,
            "primary_question": plan.surface_plan.primary_question,
            "data_boundary_notice": plan.surface_plan.data_boundary_notice,
            "metrics": [
                {"label": "Rule signals", "value": f"{len(rules)} items", "tone": "blue"},
                {"label": "Needs review", "value": f"{len(review_queue)} items", "tone": "gold"},
                {"label": "May affect", "value": f"{len(affected_client_ids)} clients", "tone": "red" if affected_client_ids else "green"},
            ],
            "rule_signals": rule_signals,
            "impacted_deadlines": impacted_deadlines,
        }
        actions = [
            {
                "label": "View rule review queue",
                "action": {
                    "type": "direct_execute",
                    "expected_view": "ReviewQueueCard",
                    "plan": {
                        "plan": [
                            {
                                "step_id": "s1",
                                "type": "cli_call",
                                "cli_group": "rule",
                                "cli_command": "review-queue",
                                "args": {},
                            }
                        ],
                        "intent_label": "rule_review",
                        "op_class": "read",
                    },
                },
            },
            {
                "label": "View upcoming deadlines",
                "action": {
                    "type": "direct_execute",
                    "expected_view": "ListCard",
                    "plan": {
                        "plan": [
                            {
                                "step_id": "s1",
                                "type": "cli_call",
                                "cli_group": "deadline",
                                "cli_command": "list",
                                "args": {"tenant_id": session.get("tenant_id"), "within_days": 30, "status": "pending"},
                            }
                        ],
                        "intent_label": "upcoming_deadlines",
                        "op_class": "read",
                    },
                },
            },
        ]
        message = (
            f"I organized the available data as a tax change radar: {len(rules)} internal rules, "
            f"{len(review_queue)} rules needing review, {len(notices)} notices, "
            f"and {len(affected_client_ids)} clients with upcoming pending deadlines. "
            "No real-time external tax news feed is connected."
        )
        return {
            "message": self._truncate_message(message),
            "view": {
                "type": "TaxChangeRadarCard",
                "data": data,
                "selectable_items": [
                    self.response_generator._to_selectable(index, item)
                    for index, item in enumerate(deadlines[:10], start=1)
                    if item.get("deadline_id") and item.get("client_id")
                ],
            },
            "actions": actions,
            "state_summary": f"{plan.surface_plan.surface_kind}: {plan.need.goal}",
        }

    def _compose_planned_render_spec(
        self,
        plan: WorkSurfacePlan,
        user_input: str,
    ) -> dict[str, Any]:
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "surface_kind": plan.surface_plan.surface_kind,
            "title": plan.surface_plan.title,
            "intent_summary": plan.surface_plan.primary_question or user_input,
            "data_boundary_notice": plan.surface_plan.data_boundary_notice,
            "blocks": [
                {"type": "decision_brief", "title": "Conclusion", "body": plan.need.goal},
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
            "rules": [],
            "review_queue": [],
            "notices": [],
            "selectable_items": [],
        }
        if "current_view" in requests:
            gathered["current_view"] = session.get("current_view")
        if "visible_deadlines" in requests:
            gathered["visible_deadlines"] = self._visible_deadline_items(session)
        if "all_clients" in requests:
            gathered["all_clients"] = [
                self.response_generator._serialize_client(client)
                for client in self.engine.list_clients(tenant_id)
            ]
        if "all_deadlines" in requests:
            gathered["all_deadlines"] = [
                self.response_generator._enrich_deadline_item(deadline, session)
                for deadline in self.engine.list_deadlines(tenant_id, status=DeadlineStatus.PENDING, limit=200)
            ]
        if "client_deadlines" in requests:
            client_id = self._selected_client_id(session)
            if client_id:
                gathered["client_deadlines"] = [
                    self.response_generator._enrich_deadline_item(deadline, session)
                    for deadline in self.engine.list_deadlines(tenant_id, client_id=client_id, status=DeadlineStatus.PENDING, limit=100)
                ]
        if "rules" in requests:
            gathered["rules"] = [self._serialize_record(rule) for rule in self.engine.list_rules()]
        if "rule_review_queue" in requests:
            gathered["review_queue"] = [self.response_generator._serialize_rule_review_item(item) for item in self.engine.list_rule_review_queue()]
        if "notices" in requests and hasattr(self.engine, "list_notices"):
            gathered["notices"] = [
                self._serialize_record(item)
                for item in self.engine.list_notices(tenant_id, limit=50)
            ]

        deadline_pool = gathered["visible_deadlines"] or gathered["client_deadlines"] or gathered["all_deadlines"]
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
        if any(term in semantic_text for term in ["taxchangeradar", "tax_change", "tax news", "policy", "notice", "rule change", "政策", "税务", "税法", "规则", "法规"]):
            requests.update({"rules", "rule_review_queue", "notices", "all_clients", "all_deadlines"})
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
        if any("\u4e00" <= char <= "\u9fff" for char in goal):
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
        if not goal or any("\u4e00" <= char <= "\u9fff" for char in goal):
            return str(decision.need_type or "Decide the next step").replace("_", " ")
        return goal

    def _english_agent_answer(self, decision: AgentKernelDecision) -> str | None:
        answer = str(decision.answer or "").strip()
        if not answer or any("\u4e00" <= char <= "\u9fff" for char in answer):
            return None
        return answer

    def _strategy_choices(self, decision: AgentKernelDecision) -> list[dict[str, str]]:
        actions = decision.suggested_actions or []
        if actions:
            return [self._english_choice(action, index) for index, action in enumerate(actions[:3])]
        if decision.next_step:
            label = decision.next_step[:48]
            if any("\u4e00" <= char <= "\u9fff" for char in label):
                label = "Continue"
            return [{"label": label, "intent": decision.next_step, "style": "primary"}]
        return [{"label": "Back to today's queue", "intent": "View today's queue", "style": "secondary"}]

    def _english_choice(self, action: dict[str, str], index: int) -> dict[str, str]:
        label = str(action.get("label") or "").strip()
        intent = str(action.get("intent") or label or "Continue").strip()
        style = str(action.get("style") or ("primary" if index == 0 else "secondary"))
        if not label or any("\u4e00" <= char <= "\u9fff" for char in label):
            semantic = f"{label} {intent}".casefold()
            label = "Open highest-risk client" if any(term in semantic for term in ["风险最高", "highest-risk", "highest risk"]) else "Continue"
        return {"label": label, "intent": intent, "style": style}

    def _serialize_record(self, record: Any) -> dict[str, Any]:
        if is_dataclass(record):
            raw = asdict(record)
        elif isinstance(record, dict):
            raw = dict(record)
        else:
            raw = dict(getattr(record, "__dict__", {}))
        return {key: self._json_safe(value) for key, value in raw.items()}

    def _json_safe(self, value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        return value

    def _truncate_message(self, message: str, limit: int = 360) -> str:
        return message if len(message) <= limit else message[: limit - 1] + "…"
