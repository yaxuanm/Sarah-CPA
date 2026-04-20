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
                    "consequence": None,
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

    def _build_generic_list_response(self, final_data: Any, session: dict[str, Any], intent_label: str) -> dict[str, Any]:
        items = final_data if isinstance(final_data, list) else [final_data]
        message = f"{intent_label} 返回 {len(items)} 条结果。"
        return {
            "message": self._truncate(message),
            "view": {
                "type": "GuidanceCard",
                "data": {"message": message, "options": [], "context_options": []},
                "selectable_items": [],
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
