from __future__ import annotations

from dataclasses import asdict, is_dataclass
import re
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
        message = decision.answer or self._strategy_message(decision, gathered)
        choices = self._strategy_choices(decision)
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "title": title,
            "intent_summary": user_input,
            "blocks": [
                {"type": "decision_brief", "title": "结论", "body": body},
                {"type": "fact_strip", "facts": facts},
                {"type": "source_list", "sources": sources},
                {"type": "choice_set", "question": "下一步怎么推进？", "choices": choices},
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
        raw_deadlines = sorted(
            gathered.get("deadline_pool", []),
            key=lambda item: (item.get("due_date") or "", item.get("client_name") or ""),
        )
        active_rules = [] if (review_queue or notices) else rules
        review_impacts = self._review_impacts(review_queue, gathered.get("all_clients", []))
        signal_keys = self._tax_change_signal_keys(
            active_rules,
            review_queue,
            notices,
            semantic_text=f"{decision.need_type} {decision.view_goal} {decision.answer}",
        )
        deadlines = self._filter_deadlines_for_signals(raw_deadlines, signal_keys)
        affected_client_ids = {item.get("client_id") for item in deadlines if item.get("client_id")}
        affected_client_ids.update(item.get("client_name") or item.get("client_id") for item in review_impacts if item.get("client_name") or item.get("client_id"))

        rule_signals: list[dict[str, str]] = []
        seen_signals: set[tuple[str, str, str]] = set()
        for rule in active_rules:
            if not self._record_matches_signal_keys(rule, signal_keys):
                continue
            self._append_unique_rule_signal(
                rule_signals,
                seen_signals,
                {
                    "title": f"{rule.get('jurisdiction') or '未知辖区'} · {rule.get('tax_type') or '规则'}",
                    "detail": f"当前截止日 {rule.get('deadline_date') or '未知'}",
                    "source": rule.get("source_url") or "未记录来源",
                },
            )
        for review in review_queue:
            payload = review.get("parse_payload") if isinstance(review.get("parse_payload"), dict) else {}
            if not self._record_matches_signal_keys(payload, signal_keys):
                continue
            self._append_unique_rule_signal(
                rule_signals,
                seen_signals,
                {
                    "title": (
                        f"{payload.get('jurisdiction') or '待审核规则'} · {payload.get('tax_type') or review.get('review_id') or '规则'}"
                    ),
                    "detail": f"置信度 {review.get('confidence_score', '未知')}",
                    "source": review.get("source_url") or "未记录来源",
                },
            )
        for notice in notices:
            if not self._record_matches_signal_keys(notice, signal_keys):
                continue
            self._append_unique_rule_signal(
                rule_signals,
                seen_signals,
                {
                    "title": notice.get("title") or notice.get("notice_id") or "Notice",
                    "detail": notice.get("summary") or "无摘要",
                    "source": notice.get("source_url") or "未记录来源",
                },
            )
        if not rule_signals:
            rule_signals.append(
                {
                    "title": "内部规则库暂无新增信号",
                    "detail": "没有发现规则审核项或 notice 记录；这不代表外部没有税务新闻。",
                    "source": "内部规则库",
                }
            )

        data = {
            "title": "本月税务变化雷达",
            "primary_question": decision.view_goal or "有哪些政策、规则或 notice 可能影响当前客户？",
            "data_boundary_notice": "当前没有实时外部税务新闻源；以下结果仅来自内部规则库、规则审核队列、notice 记录和客户 deadline。",
            "metrics": [
                {"label": "规则信号", "value": f"{len(rule_signals)} 条", "tone": "blue"},
                {"label": "待审核", "value": f"{len(review_queue)} 条", "tone": "gold"},
                {"label": "可能影响", "value": f"{len(affected_client_ids)} 个客户", "tone": "red" if affected_client_ids else "green"},
            ],
            "rule_signals": rule_signals[:6],
            "review_impacts": review_impacts[:8],
            "impacted_deadlines": [
                {
                    "client_name": item.get("client_name") or item.get("client_id") or f"客户 {index}",
                    "tax_type": item.get("tax_type") or "deadline",
                    "jurisdiction": item.get("jurisdiction") or "未知辖区",
                    "due_date": item.get("due_date") or "未知",
                    "status": item.get("status") or "unknown",
                    "deadline_id": item.get("deadline_id"),
                    "client_id": item.get("client_id"),
                }
                for index, item in enumerate(deadlines[:8], start=1)
            ],
        }
        message = decision.answer or (
            f"我按税务变化雷达整理了当前可用数据：内部规则库 {len(rule_signals)} 条、"
            f"待审核规则 {len(review_queue)} 条、notice {len(notices)} 条，"
            f"关联到 {len(affected_client_ids)} 个需要关注的客户。"
            "当前没有实时外部税务新闻源。"
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
                    "label": "查看规则审核队列",
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
                    "label": "查看近期截止日",
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
        raw_deadlines = sorted(
            evidence.get("deadlines", []),
            key=lambda item: (item.get("due_date") or "", item.get("client_id") or ""),
        )
        active_rules = [] if (review_queue or notices) else rules
        review_impacts = self._review_impacts(review_queue, clients)
        signal_keys = self._tax_change_signal_keys(
            active_rules,
            review_queue,
            notices,
            semantic_text=f"{plan.need.goal} {plan.surface_plan.primary_question}",
        )
        deadlines = self._filter_deadlines_for_signals(raw_deadlines, signal_keys)
        affected_client_ids = {item.get("client_id") for item in deadlines if item.get("client_id")}
        affected_client_ids.update(item.get("client_name") or item.get("client_id") for item in review_impacts if item.get("client_name") or item.get("client_id"))

        rule_signals: list[dict[str, str]] = []
        seen_signals: set[tuple[str, str, str]] = set()
        for rule in active_rules:
            if not self._record_matches_signal_keys(rule, signal_keys):
                continue
            self._append_unique_rule_signal(
                rule_signals,
                seen_signals,
                {
                    "title": f"{rule.get('jurisdiction') or '未知辖区'} · {rule.get('tax_type') or '规则'}",
                    "detail": f"当前截止日 {rule.get('deadline_date') or '未知'}",
                    "source": rule.get("source_url") or "未记录来源",
                },
            )
        for review in review_queue:
            payload = review.get("parse_payload") if isinstance(review.get("parse_payload"), dict) else {}
            if not self._record_matches_signal_keys(payload, signal_keys):
                continue
            self._append_unique_rule_signal(
                rule_signals,
                seen_signals,
                {
                    "title": (
                        f"{payload.get('jurisdiction') or '待审核规则'} · {payload.get('tax_type') or review.get('review_id') or '规则'}"
                    ),
                    "detail": f"置信度 {review.get('confidence_score', '未知')}",
                    "source": review.get("source_url") or "未记录来源",
                },
            )
        for notice in notices:
            if not self._record_matches_signal_keys(notice, signal_keys):
                continue
            self._append_unique_rule_signal(
                rule_signals,
                seen_signals,
                {
                    "title": notice.get("title") or notice.get("notice_id") or "Notice",
                    "detail": notice.get("summary") or "无摘要",
                    "source": notice.get("source_url") or "未记录来源",
                },
            )
        if not rule_signals:
            rule_signals.append(
                {
                    "title": "内部规则库暂无新增信号",
                    "detail": "没有发现规则审核项或 notice 记录；这不代表外部没有税务新闻。",
                    "source": "内部规则库",
                }
            )

        impacted_deadlines = [
            {
                "client_name": client_names.get(item.get("client_id")) or item.get("client_id") or f"客户 {index}",
                "tax_type": item.get("tax_type") or "deadline",
                "jurisdiction": item.get("jurisdiction") or "未知辖区",
                "due_date": item.get("due_date") or "未知",
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
                {"label": "规则信号", "value": f"{len(rule_signals)} 条", "tone": "blue"},
                {"label": "待审核", "value": f"{len(review_queue)} 条", "tone": "gold"},
                {"label": "可能影响", "value": f"{len(affected_client_ids)} 个客户", "tone": "red" if affected_client_ids else "green"},
            ],
            "rule_signals": rule_signals[:6],
            "review_impacts": review_impacts[:8],
            "impacted_deadlines": impacted_deadlines,
        }
        actions = [
            {
                "label": "查看规则审核队列",
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
                "label": "查看近期截止日",
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
            f"我按税务变化雷达整理了当前可用数据：内部规则库 {len(rule_signals)} 条、"
            f"待审核规则 {len(review_queue)} 条、notice {len(notices)} 条，"
            f"关联到 {len(affected_client_ids)} 个需要关注的客户。"
            "当前没有实时外部税务新闻源。"
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

    def _tax_change_signal_keys(
        self,
        rules: list[dict[str, Any]],
        review_queue: list[dict[str, Any]],
        notices: list[dict[str, Any]],
        semantic_text: str = "",
    ) -> set[tuple[str | None, str | None]]:
        keys: set[tuple[str | None, str | None]] = set()
        for rule in rules:
            keys.add((self._normalize_jurisdiction(rule.get("jurisdiction")), self._normalize_tax_type(rule.get("tax_type"))))
        for review in review_queue:
            payload = review.get("parse_payload") if isinstance(review.get("parse_payload"), dict) else {}
            keys.add((self._normalize_jurisdiction(payload.get("jurisdiction")), self._normalize_tax_type(payload.get("tax_type"))))
        for notice in notices:
            jurisdiction = notice.get("jurisdiction") or notice.get("state")
            tax_type = notice.get("tax_type")
            keys.add((self._normalize_jurisdiction(jurisdiction), self._normalize_tax_type(tax_type)))
        keys = {(jurisdiction, tax_type) for jurisdiction, tax_type in keys if jurisdiction or tax_type}
        focus_jurisdictions, focus_tax_types = self._tax_change_focus(semantic_text)
        if focus_jurisdictions or focus_tax_types:
            focused = {
                (jurisdiction, tax_type)
                for jurisdiction, tax_type in keys
                if (not focus_jurisdictions or jurisdiction in focus_jurisdictions)
                and (not focus_tax_types or tax_type in focus_tax_types)
            }
            return focused or keys
        return keys

    def _review_impacts(self, review_queue: list[dict[str, Any]], clients: list[dict[str, Any]]) -> list[dict[str, Any]]:
        impacts: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for review in review_queue:
            payload = review.get("parse_payload") if isinstance(review.get("parse_payload"), dict) else {}
            jurisdiction = self._normalize_jurisdiction(payload.get("jurisdiction"))
            tax_type = payload.get("tax_type") or "rule change"
            entity_types = {
                self._normalize_entity_type(entity_type)
                for entity_type in (payload.get("entity_types") or [])
                if entity_type
            }
            for client in clients:
                client_id = client.get("client_id") or client.get("id")
                client_name = client.get("name") or client_id
                client_entity = self._normalize_entity_type(client.get("entity_type"))
                states = [
                    self._normalize_jurisdiction(state)
                    for state in (client.get("registered_states") or client.get("states") or [])
                ]
                if jurisdiction and jurisdiction not in states:
                    continue
                if entity_types and client_entity not in entity_types:
                    continue
                key = (str(review.get("review_id") or tax_type), str(client_name or client_id))
                if key in seen:
                    continue
                seen.add(key)
                impacts.append(
                    {
                        "client_id": client_id,
                        "client_name": client_name or "未知客户",
                        "tax_type": tax_type,
                        "jurisdiction": payload.get("jurisdiction") or "未知辖区",
                        "due_date": payload.get("deadline_date") or "待确认",
                        "status": "needs review",
                        "source": review.get("source_url") or "未记录来源",
                    }
                )
        return impacts

    def _normalize_entity_type(self, value: Any) -> str | None:
        if value is None:
            return None
        return re.sub(r"[^a-z0-9]+", "-", str(value).strip().casefold()).strip("-")

    def _filter_deadlines_for_signals(
        self,
        deadlines: list[dict[str, Any]],
        signal_keys: set[tuple[str | None, str | None]],
    ) -> list[dict[str, Any]]:
        if not signal_keys:
            return []
        matched: list[dict[str, Any]] = []
        seen: set[str] = set()
        for deadline in deadlines:
            jurisdiction = self._normalize_jurisdiction(deadline.get("jurisdiction"))
            tax_type = self._normalize_tax_type(deadline.get("tax_type"))
            if not any(
                (not signal_jurisdiction or signal_jurisdiction == jurisdiction)
                and (not signal_tax_type or signal_tax_type == tax_type)
                for signal_jurisdiction, signal_tax_type in signal_keys
            ):
                continue
            identity = str(
                deadline.get("deadline_id")
                or "|".join(
                    [
                        str(deadline.get("client_id") or ""),
                        str(deadline.get("tax_type") or ""),
                        str(deadline.get("jurisdiction") or ""),
                        str(deadline.get("due_date") or ""),
                    ]
                )
            )
            if identity in seen:
                continue
            seen.add(identity)
            matched.append(deadline)
        return matched

    def _record_matches_signal_keys(self, record: dict[str, Any], signal_keys: set[tuple[str | None, str | None]]) -> bool:
        if not signal_keys:
            return True
        jurisdiction = self._normalize_jurisdiction(record.get("jurisdiction") or record.get("state"))
        tax_type = self._normalize_tax_type(record.get("tax_type"))
        return any(
            (not signal_jurisdiction or signal_jurisdiction == jurisdiction)
            and (not signal_tax_type or signal_tax_type == tax_type)
            for signal_jurisdiction, signal_tax_type in signal_keys
        )

    def _append_unique_rule_signal(
        self,
        signals: list[dict[str, str]],
        seen: set[tuple[str, str, str]],
        signal: dict[str, Any],
    ) -> None:
        title = str(signal.get("title") or "").strip()
        detail = str(signal.get("detail") or "").strip()
        source = str(signal.get("source") or "").strip()
        identity = (self._normalize_signal_text(title), self._normalize_signal_text(detail), source)
        if not title or identity in seen:
            return
        seen.add(identity)
        signals.append({"title": title, "detail": detail, "source": source})

    @staticmethod
    def _normalize_jurisdiction(value: Any) -> str | None:
        text = str(value or "").strip().upper()
        return text or None

    @staticmethod
    def _normalize_tax_type(value: Any) -> str | None:
        text = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
        aliases = {
            "sales_use": "sales_use",
            "sales": "sales_use",
            "sales_tax": "sales_use",
            "payroll_941": "payroll",
            "941": "payroll",
            "pte": "pte_election",
            "pte_election": "pte_election",
            "franchise": "franchise_tax",
            "franchise_tax": "franchise_tax",
            "federal_income": "federal_income",
            "state_income": "state_income",
        }
        return aliases.get(text, text or None)

    @staticmethod
    def _normalize_signal_text(value: str) -> str:
        return re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", "<id>", value.casefold()).strip()

    def _tax_change_focus(self, semantic_text: str) -> tuple[set[str], set[str]]:
        text = semantic_text.casefold()
        jurisdictions = {
            code
            for code, terms in {
                "CA": [" ca ", "california", "加州"],
                "TX": [" tx ", "texas", "德州"],
                "NY": [" ny ", "new york", "纽约"],
            }.items()
            if any(term in f" {text} " for term in terms)
        }
        tax_types = {
            normalized
            for normalized, terms in {
                "franchise_tax": ["franchise", "特许"],
                "sales_use": ["sales", "sales/use", "sales tax", "销售税"],
                "pte_election": ["pte", "pass-through", "pass through"],
                "federal_income": ["federal income"],
                "state_income": ["state income"],
                "payroll": ["payroll", "941"],
            }.items()
            if any(term in text for term in terms)
        }
        return jurisdictions, tax_types

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
                {"type": "decision_brief", "title": "结论", "body": plan.need.goal},
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
        return [{"label": "当前页面", "detail": "我先基于当前页面给出判断；如果你要更细的依据，可以继续追问。"}]

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
