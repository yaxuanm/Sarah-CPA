from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .engine import InfrastructureEngine


ACTION_LABELS = {
    "complete": "标记完成",
    "snooze": "稍后提醒",
    "waive": "标记不适用",
    "reopen": "撤销",
    "override": "修改日期",
}

INTENT_RELEVANT_ACTIONS = {
    "client_deadline_list": {"complete", "snooze", "waive", "override", "reopen"},
    "today": {"complete", "snooze", "waive", "override"},
}


class ResponseGenerator:
    def __init__(self, engine: InfrastructureEngine) -> None:
        self.engine = engine

    def generate(self, executor_result: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        intent_label = executor_result.get("intent_label", "unknown")
        final_data = executor_result.get("final_data", [])
        op_class = executor_result.get("op_class", "read")

        if op_class == "write":
            raise ValueError("write plans must be rendered via generate_confirm_card before execution")

        if intent_label == "today":
            return self._build_today_response(final_data, session)
        if intent_label == "client_deadline_list":
            return self._build_client_deadline_response(final_data, session)
        if intent_label == "deadline_history":
            return self._build_deadline_history_response(final_data, session)
        if intent_label in {"upcoming_deadlines", "completed_deadlines"}:
            return self._build_deadline_collection_response(final_data, session, intent_label)
        if intent_label == "notification_preview":
            return self._build_notification_preview_response(final_data, session)
        if intent_label == "client_list":
            return self._build_client_list_response(final_data, session)
        if intent_label == "rule_review":
            return self._build_rule_review_response(final_data)
        return self._build_generic_list_response(final_data, session, intent_label)

    def generate_confirm_card(self, plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        step = next(step for step in plan["plan"] if step["type"] == "cli_call" and step["cli_group"] == "deadline" and step["cli_command"] == "action")
        args = step["args"]
        deadline = self._serialize_deadline(self.engine.get_deadline(args["tenant_id"], args["deadline_id"]))
        client = self._client_map(args["tenant_id"]).get(deadline["client_id"])
        client_name = client["name"] if client else deadline["client_id"]
        label = ACTION_LABELS.get(args["action"], args["action"])
        selectable_items = [
            {
                "ref": "item_1",
                "deadline_id": deadline["deadline_id"],
                "client_id": deadline["client_id"],
                "client_name": client_name,
            }
        ]
        return {
            "message": self._truncate(f"确认执行：{client_name}{label}，截止日 {deadline['due_date']}。"),
            "view": {
                "type": "ConfirmCard",
                "data": {
                    "description": f"{client_name} — {deadline['tax_type']}",
                    "due_date": deadline["due_date"],
                    "consequence": f"确认后会把这条截止事项{label}；取消则不改动任何数据。",
                    "options": [
                        {"label": f"确认{label.replace('标记', '')}", "style": "primary", "plan": plan},
                        {"label": "取消", "style": "secondary", "plan": None},
                    ],
                },
                "selectable_items": selectable_items,
            },
            "actions": [],
            "state_summary": None,
        }

    def generate_guidance(self, message: str, options: list[str], context_options: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "message": self._truncate(message),
            "view": {
                "type": "GuidanceCard",
                "data": {
                    "message": message,
                    "options": options,
                    "context_options": context_options or [],
                },
                "selectable_items": context_options or [],
            },
            "actions": [],
            "state_summary": None,
        }

    def _build_today_response(self, final_data: list[dict[str, Any]], session: dict[str, Any]) -> dict[str, Any]:
        items = [self._enrich_today_item(item, session) for item in final_data]
        items.sort(key=lambda item: (item["days_remaining"], item["due_date"]))
        visible = items[:5]
        selectable_items = [self._to_selectable(index, item) for index, item in enumerate(visible, start=1)]
        message = "今天没有待处理事项。" if not items else f"当前有 {len(items)} 件待处理，最早 {items[0]['due_date']} 到期。"
        return {
            "message": self._truncate(message),
            "view": {
                "type": "ListCard",
                "data": {"items": visible, "total": len(items), "has_more": len(items) > 5},
                "selectable_items": selectable_items,
            },
            "actions": self._build_actions(session["tenant_id"], visible[0]["deadline_id"], "today") if visible else [],
            "state_summary": None if not items else f"显示 {len(visible)} / {len(items)} 条待处理事项。",
        }

    def _build_client_deadline_response(self, final_data: list[dict[str, Any]], session: dict[str, Any]) -> dict[str, Any]:
        enriched_deadlines = [self._enrich_deadline_item(item, session) for item in final_data]
        enriched_deadlines.sort(key=lambda item: (item["due_date"], item["deadline_id"]))
        if not enriched_deadlines:
            return self.generate_guidance("没有找到该客户的截止日期。", ["查看今天的待处理事项"])

        client_map = self._client_map(session["tenant_id"])
        client = client_map.get(enriched_deadlines[0]["client_id"])
        client_name = client["name"] if client else enriched_deadlines[0]["client_id"]
        selectable_items = [self._to_selectable(index, item, client_name=client_name) for index, item in enumerate(enriched_deadlines, start=1)]
        return {
            "message": self._truncate(f"{client_name} 有 {len(enriched_deadlines)} 个截止日期，最近 {enriched_deadlines[0]['due_date']}。"),
            "view": {
                "type": "ClientCard",
                "data": {
                    "client_id": enriched_deadlines[0]["client_id"],
                    "client_name": client_name,
                    "entity_type": client["entity_type"] if client else None,
                    "registered_states": client["registered_states"] if client else [],
                    "deadlines": enriched_deadlines,
                },
                "selectable_items": selectable_items,
            },
            "actions": self._build_actions(session["tenant_id"], enriched_deadlines[0]["deadline_id"], "client_deadline_list"),
            "state_summary": f"显示 {client_name} 的 {len(enriched_deadlines)} 个截止日期。",
        }

    def _build_deadline_history_response(self, final_data: Any, session: dict[str, Any]) -> dict[str, Any]:
        transitions = [self._serialize_transition(item) for item in final_data] if isinstance(final_data, list) else []
        selected = (session.get("selectable_items") or [{}])[0]
        deadline_id = selected.get("deadline_id") or (transitions[0]["deadline_id"] if transitions else None)
        deadline = self._serialize_deadline(self.engine.get_deadline(session["tenant_id"], deadline_id)) if deadline_id else {}
        client = self._client_map(session["tenant_id"]).get(deadline.get("client_id"))
        rules = {rule.rule_id: rule for rule in self.engine.list_rules()}
        rule = rules.get(deadline.get("rule_id"))
        client_name = client["name"] if client else selected.get("client_name")
        selectable_items = [selected] if selected else []
        source_url = rule.source_url if rule else None
        message = (
            f"{client_name} 这条记录来自规则来源，当前有 {len(transitions)} 条变更记录。"
            if source_url
            else f"{client_name or '当前事项'} 当前有 {len(transitions)} 条变更记录。"
        )
        return {
            "message": self._truncate(message),
            "view": {
                "type": "HistoryCard",
                "data": {
                    "client_name": client_name,
                    "deadline_id": deadline.get("deadline_id"),
                    "tax_type": deadline.get("tax_type"),
                    "jurisdiction": deadline.get("jurisdiction"),
                    "due_date": deadline.get("due_date"),
                    "status": deadline.get("status"),
                    "source_url": source_url,
                    "transitions": transitions,
                },
                "selectable_items": selectable_items,
            },
            "actions": [],
            "state_summary": f"显示 {client_name or '当前事项'} 的来源和变更记录。",
        }

    def _build_deadline_collection_response(
        self,
        final_data: Any,
        session: dict[str, Any],
        intent_label: str,
    ) -> dict[str, Any]:
        items = [self._enrich_deadline_item(item, session) for item in final_data] if isinstance(final_data, list) else []
        items.sort(key=lambda item: (item["due_date"], item["deadline_id"]))
        visible = items[:10]
        client_map = self._client_map(session["tenant_id"])
        for item in visible:
            client = client_map.get(item["client_id"])
            item["client_name"] = client["name"] if client else item["client_id"]
        selectable_items = [self._to_selectable(index, item) for index, item in enumerate(visible, start=1)]
        title = "未来待处理截止事项" if intent_label == "upcoming_deadlines" else "已完成截止事项"
        return {
            "message": self._truncate(f"{title}：{len(items)} 条。"),
            "view": {
                "type": "ListCard",
                "data": {"items": visible, "total": len(items), "has_more": len(items) > 10},
                "selectable_items": selectable_items,
            },
            "actions": [],
            "state_summary": f"显示 {len(visible)} / {len(items)} 条{title}。",
        }

    def _build_notification_preview_response(self, final_data: Any, session: dict[str, Any]) -> dict[str, Any]:
        reminders = [self._serialize_reminder(item) for item in final_data] if isinstance(final_data, list) else []
        client_map = self._client_map(session["tenant_id"])
        deadline_map = {
            deadline.deadline_id: self._serialize_deadline(deadline)
            for deadline in self.engine.list_deadlines(session["tenant_id"])
        }
        for reminder in reminders:
            deadline = deadline_map.get(reminder["deadline_id"], {})
            client = client_map.get(reminder["client_id"])
            reminder["client_name"] = client["name"] if client else reminder["client_id"]
            reminder["tax_type"] = deadline.get("tax_type")
            reminder["due_date"] = deadline.get("due_date")
        return {
            "message": self._truncate(f"接下来需要提醒 {len(reminders)} 项。"),
            "view": {
                "type": "ReminderPreviewCard",
                "data": {"reminders": reminders, "total": len(reminders)},
                "selectable_items": [
                    {
                        "ref": f"item_{index}",
                        "deadline_id": reminder["deadline_id"],
                        "client_id": reminder["client_id"],
                        "client_name": reminder.get("client_name"),
                    }
                    for index, reminder in enumerate(reminders[:10], start=1)
                ],
            },
            "actions": [],
            "state_summary": f"显示 {len(reminders)} 项待提醒事项。",
        }

    def _build_client_list_response(self, final_data: Any, session: dict[str, Any]) -> dict[str, Any]:
        clients = [self._serialize_client(item) for item in final_data] if isinstance(final_data, list) else []
        clients.sort(key=lambda item: item["name"])
        return {
            "message": self._truncate(f"共有 {len(clients)} 个客户。"),
            "view": {
                "type": "ClientListCard",
                "data": {"clients": clients, "total": len(clients)},
                "selectable_items": [
                    {"ref": f"client_{index}", "client_id": client["client_id"], "client_name": client["name"]}
                    for index, client in enumerate(clients, start=1)
                ],
            },
            "actions": [],
            "state_summary": f"显示 {len(clients)} 个客户。",
        }

    def _build_rule_review_response(self, final_data: Any) -> dict[str, Any]:
        review_items = [self._serialize_rule_review_item(item) for item in final_data] if isinstance(final_data, list) else []
        return {
            "message": self._truncate(f"有 {len(review_items)} 条规则需要审核。"),
            "view": {
                "type": "ReviewQueueCard",
                "data": {"items": review_items, "total": len(review_items)},
                "selectable_items": [
                    {"ref": f"review_{index}", "review_id": item["review_id"], "source_url": item["source_url"]}
                    for index, item in enumerate(review_items, start=1)
                ],
            },
            "actions": [],
            "state_summary": f"显示 {len(review_items)} 条规则审核项。",
        }

    def _build_generic_list_response(self, final_data: Any, session: dict[str, Any], intent_label: str) -> dict[str, Any]:
        items = final_data if isinstance(final_data, list) else [final_data]
        message = f"{intent_label} 返回 {len(items)} 条结果。"
        selectable_items = session.get("selectable_items", [])
        return {
            "message": self._truncate(message),
            "view": {
                "type": "GuidanceCard",
                "data": {"message": message, "options": [], "context_options": selectable_items},
                "selectable_items": selectable_items,
            },
            "actions": [],
            "state_summary": None,
        }

    def _build_actions(self, tenant_id: str, deadline_id: str, intent_label: str) -> list[dict[str, Any]]:
        available = self.engine.available_deadline_actions(tenant_id, deadline_id)
        allowed = INTENT_RELEVANT_ACTIONS.get(intent_label, set())
        actions = []
        for action in available["available_actions"]:
            if action not in allowed:
                continue
            entry = {
                "label": ACTION_LABELS.get(action, action),
                "plan": {
                    "plan": [
                        {
                            "step_id": "s1",
                            "type": "cli_call",
                            "cli_group": "deadline",
                            "cli_command": "action",
                            "args": {
                                "tenant_id": tenant_id,
                                "deadline_id": deadline_id,
                                "action": action,
                            },
                        }
                    ],
                    "op_class": "write",
                    "intent_label": f"deadline_action_{action}",
                },
            }
            actions.append(entry)
            if len(actions) == 3:
                break
        return actions

    def _enrich_today_item(self, item: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        if "days_remaining" not in payload:
            payload["days_remaining"] = self._days_remaining(payload["due_date"], session["today"])
        return payload

    def _enrich_deadline_item(self, item: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        payload = self._serialize_deadline(item)
        payload["days_remaining"] = self._days_remaining(payload["due_date"], session["today"])
        payload["available_actions"] = self.engine.available_deadline_actions(session["tenant_id"], payload["deadline_id"])["available_actions"]
        return payload

    def _client_map(self, tenant_id: str) -> dict[str, dict[str, Any]]:
        return {
            client["client_id"]: client
            for client in [self._serialize_client(item) for item in self.engine.list_clients(tenant_id)]
        }

    def _serialize_deadline(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return dict(item)
        return {
            "deadline_id": item.deadline_id,
            "client_id": item.client_id,
            "tenant_id": item.tenant_id,
            "rule_id": item.rule_id,
            "tax_type": item.tax_type,
            "jurisdiction": item.jurisdiction,
            "due_date": item.due_date,
            "status": item.status.value,
        }

    def _serialize_client(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return dict(item)
        return {
            "client_id": item.client_id,
            "tenant_id": item.tenant_id,
            "name": item.name,
            "entity_type": item.entity_type,
            "registered_states": item.registered_states,
        }

    def _serialize_transition(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            payload = dict(item)
        else:
            payload = {
                "transition_id": item.transition_id,
                "deadline_id": item.deadline_id,
                "tenant_id": item.tenant_id,
                "previous_status": item.previous_status,
                "new_status": item.new_status,
                "action": item.action,
                "actor": item.actor,
                "metadata": item.metadata,
                "created_at": item.created_at,
            }
        if isinstance(payload.get("created_at"), datetime):
            payload["created_at"] = payload["created_at"].isoformat()
        return payload

    def _serialize_reminder(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            payload = dict(item)
        else:
            payload = {
                "reminder_id": item.reminder_id,
                "deadline_id": item.deadline_id,
                "tenant_id": item.tenant_id,
                "client_id": item.client_id,
                "scheduled_at": item.scheduled_at,
                "triggered_at": item.triggered_at,
                "status": item.status.value,
                "reminder_day": item.reminder_day,
                "reminder_type": item.reminder_type.value,
                "responded_at": item.responded_at,
                "response": item.response,
            }
        for key in ["scheduled_at", "triggered_at", "responded_at"]:
            if isinstance(payload.get(key), datetime):
                payload[key] = payload[key].isoformat()
        return payload

    def _serialize_rule_review_item(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            payload = dict(item)
        else:
            payload = {
                "review_id": item.review_id,
                "source_url": item.source_url,
                "fetched_at": item.fetched_at,
                "raw_text": item.raw_text,
                "confidence_score": item.confidence_score,
                "created_at": item.created_at,
                "parse_payload": item.parse_payload,
            }
        for key in ["fetched_at", "created_at"]:
            if isinstance(payload.get(key), datetime):
                payload[key] = payload[key].isoformat()
        return payload

    def _to_selectable(self, index: int, item: dict[str, Any], client_name: str | None = None) -> dict[str, Any]:
        return {
            "ref": f"item_{index}",
            "deadline_id": item["deadline_id"],
            "client_id": item["client_id"],
            "client_name": client_name or item.get("client_name"),
        }

    def _days_remaining(self, due_date: str, today_value: str) -> int:
        due = date.fromisoformat(due_date)
        today = date.fromisoformat(today_value)
        return (due - today).days

    def _truncate(self, text: str, max_chars: int = 50) -> str:
        return text if len(text) <= max_chars else f"{text[: max_chars - 1]}…"
