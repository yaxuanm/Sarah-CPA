from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .engine import InfrastructureEngine
from .system_state import workspace_snapshot


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

    def generate_guidance(
        self,
        message: str,
        options: list[str],
        context_options: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
        title: str | None = None,
        eyebrow: str | None = None,
    ) -> dict[str, Any]:
        return {
            "message": self._truncate(message),
            "view": {
                "type": "GuidanceCard",
                "data": {
                    "title": title or "需要一点上下文",
                    "eyebrow": eyebrow or "Need one more bit of context",
                    "message": message,
                    "options": options,
                    "context_options": context_options or [],
                },
                "selectable_items": context_options or [],
            },
            "actions": actions or [],
            "state_summary": None,
        }

    def generate_render_spec_surface(
        self,
        user_input: str,
        session: dict[str, Any],
        message: str | None = None,
    ) -> dict[str, Any]:
        text = user_input.strip() or "用户提出了一个开放需求"
        selected = session.get("selectable_items") or []
        if selected and self._looks_like_draft_request(text):
            return self._build_client_message_draft_surface(text, session, selected[0])

        context_label = selected[0].get("client_name") if selected else "当前工作队列"
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "title": "我先帮你把这件事理清楚",
            "intent_summary": text,
            "blocks": [
                {
                    "type": "decision_brief",
                    "title": "我理解的是",
                    "body": (
                        f"你想继续处理 {context_label}，但这句话还没有指向某一个具体截止事项或动作。"
                        "我可以先帮你整理现状，也可以继续查依据。"
                    ),
                },
                {
                    "type": "fact_strip",
                    "facts": [
                        {"label": "当前对象", "value": str(context_label), "tone": "blue"},
                        {"label": "当前阶段", "value": "先整理，不改记录", "tone": "gold"},
                        {"label": "状态变更", "value": "尚未发生", "tone": "green"},
                    ],
                },
                {
                    "type": "choice_set",
                    "question": "如果这个工作面不对，可以直接继续说你的需求。",
                    "choices": [
                        {"label": "补充说明", "intent": "我再补充一下需求", "style": "primary"},
                        {"label": "回到今日清单", "intent": "查看今天的待处理事项", "style": "secondary"},
                    ],
                },
            ],
        }
        return {
            "message": self._truncate(message or "我先把这件事整理成一个可推进的工作面。"),
            "view": {
                "type": "RenderSpecSurface",
                "data": {"render_spec": render_spec},
                "selectable_items": selected,
            },
            "actions": [],
            "state_summary": "根据开放需求生成受约束工作面。",
        }

    def _build_client_message_draft_surface(
        self,
        user_input: str,
        session: dict[str, Any],
        selected: dict[str, Any],
    ) -> dict[str, Any]:
        deadline_id = selected.get("deadline_id")
        deadline = self._serialize_deadline(self.engine.get_deadline(session["tenant_id"], deadline_id)) if deadline_id else {}
        client = self._client_map(session["tenant_id"]).get(deadline.get("client_id"))
        client_name = client["name"] if client else selected.get("client_name") or "当前客户"
        tax_type = deadline.get("tax_type") or "当前事项"
        due_date = deadline.get("due_date") or "当前截止日"
        jurisdiction = deadline.get("jurisdiction") or "相关辖区"
        record_action = self._deadline_action_direct_action(session["tenant_id"], deadline_id, "complete") if deadline_id else None
        history_action = self._deadline_history_direct_action(session["tenant_id"], deadline_id) if deadline_id else None
        today_action = self._today_direct_action(session["tenant_id"])
        draft = (
            f"Hi,\n\n"
            f"We are working on your {tax_type} for {jurisdiction}. "
            f"The current due date is {due_date}. Could you please send over the remaining information needed for this filing?\n\n"
            f"Thank you,\nSarah"
        )
        render_spec = {
            "version": "0.1",
            "surface": "work_card",
            "title": f"{client_name} 的客户消息草稿",
            "intent_summary": user_input,
            "blocks": [
                {
                    "type": "decision_brief",
                    "title": "这是一封需要你发出去的消息",
                    "body": (
                        f"我根据当前选中的 {client_name} - {tax_type} 生成了草稿。"
                        "DueDateHQ 只生成内容，不会替你发送，也不会修改记录。"
                    ),
                },
                {
                    "type": "fact_strip",
                    "facts": [
                        {"label": "客户", "value": str(client_name), "tone": "blue"},
                        {"label": "事项", "value": str(tax_type), "tone": "gold"},
                        {"label": "截止日", "value": str(due_date), "tone": "red"},
                    ],
                },
                {
                    "type": "action_draft",
                    "label": "发送给客户的内容",
                    "body": draft,
                    "note": "请通过你的邮箱或客户 portal 发出。发出后再回来记录为已发送。",
                },
                {
                    "type": "choice_set",
                    "question": "发出之后回来记录。",
                    "choices": [
                        {
                            "label": "记录为已发送",
                            "intent": "record as sent",
                            "style": "primary",
                            "action": record_action,
                        },
                        {
                            "label": "查看依据",
                            "intent": "show source",
                            "style": "secondary",
                            "action": history_action,
                        },
                        {
                            "label": "回到今日清单",
                            "intent": "today",
                            "style": "secondary",
                            "action": today_action,
                        },
                    ],
                },
            ],
        }
        return {
            "message": self._truncate(f"我已经为 {client_name} 生成客户消息草稿。发出后再回来记录。"),
            "view": {
                "type": "RenderSpecSurface",
                "data": {"render_spec": render_spec},
                "selectable_items": [selected],
            },
            "actions": [],
            "state_summary": f"生成 {client_name} 的客户消息草稿。",
        }

    def _deadline_action_direct_action(self, tenant_id: str, deadline_id: str, action: str) -> dict[str, Any]:
        return {
            "type": "direct_execute",
            "expected_view": "ConfirmCard",
            "plan": self._deadline_action_plan(tenant_id, deadline_id, action),
        }

    def _deadline_history_direct_action(self, tenant_id: str, deadline_id: str) -> dict[str, Any]:
        return {
            "type": "direct_execute",
            "expected_view": "HistoryCard",
            "plan": self._deadline_history_plan(tenant_id, deadline_id),
        }

    def _today_direct_action(self, tenant_id: str) -> dict[str, Any]:
        return {
            "type": "direct_execute",
            "expected_view": "ListCard",
            "plan": self._today_plan(tenant_id),
        }

    def _deadline_action_plan(self, tenant_id: str, deadline_id: str, action: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "action",
                    "args": {"tenant_id": tenant_id, "deadline_id": deadline_id, "action": action},
                }
            ],
            "op_class": "write",
            "intent_label": f"deadline_action_{action}",
        }

    def _deadline_history_plan(self, tenant_id: str, deadline_id: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "transitions",
                    "args": {"tenant_id": tenant_id, "deadline_id": deadline_id},
                }
            ],
            "intent_label": "deadline_history",
            "op_class": "read",
        }

    def _today_plan(self, tenant_id: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "today",
                    "cli_command": "today",
                    "args": {"tenant_id": tenant_id, "limit": 5, "enrich": True},
                }
            ],
            "intent_label": "today",
            "op_class": "read",
        }

    def _looks_like_draft_request(self, text: str) -> bool:
        lowered = text.casefold()
        return any(
            token in lowered
            for token in [
                "draft",
                "prepare",
                "message",
                "email",
                "草稿",
                "起草",
                "客户消息",
                "邮件",
                "生成客户消息",
                "先生成草稿",
            ]
        )

    def _build_today_response(self, final_data: list[dict[str, Any]], session: dict[str, Any]) -> dict[str, Any]:
        items = [self._enrich_today_item(item, session) for item in final_data]
        items.sort(key=lambda item: (item["days_remaining"], item["due_date"]))
        visible = items[:5]
        selectable_items = [
            self._to_selectable(index, item, tenant_id=session["tenant_id"], session=session, prefetch_client=True)
            for index, item in enumerate(visible, start=1)
        ]
        self._remember_prefetch_pool(session, selectable_items)
        message = "今天没有待处理事项。" if not items else f"当前有 {len(items)} 件待处理，最早 {items[0]['due_date']} 到期。"
        return {
            "message": self._truncate(message),
            "view": {
                "type": "ListCard",
                "data": {
                    "title": "今天需要处理的事项",
                    "headline": "先看最可能卡住申报的事项",
                    "description": "这是今天最值得你注意的工作队列。打开一项后，我会只围绕那一项继续帮你处理。",
                    "items": visible,
                    "total": len(items),
                    "has_more": len(items) > 5,
                    "status_label": "待处理",
                    "suggested_prompts": ["查看所有未来截止日", "只看某个客户", "哪些需要催客户"],
                },
                "selectable_items": selectable_items,
            },
            "actions": self._build_actions(session["tenant_id"], visible[0]["deadline_id"], "today") if visible else [],
            "state_summary": None if not items else f"显示 {len(visible)} / {len(items)} 条待处理事项。",
        }

    def _build_client_deadline_response(self, final_data: Any, session: dict[str, Any]) -> dict[str, Any]:
        deadline_items = self._extract_deadline_items(final_data)
        enriched_deadlines = [self._enrich_deadline_item(item, session) for item in deadline_items]
        enriched_deadlines.sort(key=lambda item: (item["due_date"], item["deadline_id"]))
        if not enriched_deadlines:
            return self.generate_guidance("没有找到该客户的截止日期。", ["查看今天的待处理事项"])

        client_map = self._client_map(session["tenant_id"])
        bundled_client = self._extract_bundled_client(final_data)
        client = client_map.get(enriched_deadlines[0]["client_id"]) or bundled_client
        client_name = client["name"] if client else enriched_deadlines[0]["client_id"]
        selectable_items = [
            self._to_selectable(index, item, client_name=client_name, tenant_id=session["tenant_id"])
            for index, item in enumerate(enriched_deadlines, start=1)
        ]
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
        selectable_items = [
            self._to_selectable(index, item, tenant_id=session["tenant_id"], session=session, prefetch_client=True)
            for index, item in enumerate(visible, start=1)
        ]
        self._remember_prefetch_pool(session, selectable_items)
        is_upcoming = intent_label == "upcoming_deadlines"
        title = "所有未来待处理截止事项" if is_upcoming else "已完成截止事项"
        headline = "这里是还没有完成的全部未来 DDL" if is_upcoming else "这里是已经处理完的事项"
        description = (
            "我先按截止日期排序。你可以继续追问：按客户分组、只看某个客户、只看本周、或解释某一条为什么在这里。"
            if is_upcoming
            else "这些事项已经完成，只用于核对和追溯，不提供写操作。"
        )
        suggested_prompts = (
            ["按客户分组", "只看本周", "解释第一条为什么在这里"]
            if is_upcoming
            else ["查看今天待处理事项", "查看所有未来截止日"]
        )
        return {
            "message": self._truncate(f"{title}：{len(items)} 条。"),
            "view": {
                "type": "ListCard",
                "data": {
                    "title": title,
                    "headline": headline,
                    "description": description,
                    "items": visible,
                    "total": len(items),
                    "has_more": len(items) > 10,
                    "status_label": "待处理" if is_upcoming else "已完成",
                    "suggested_prompts": suggested_prompts,
                },
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
        latest_user_input = ""
        for item in reversed(session.get("history_window", [])):
            if item.get("actor") == "user":
                latest_user_input = item.get("text", "")
                break
        return self.generate_render_spec_surface(
            latest_user_input or intent_label,
            session,
            f"{intent_label} 没有命中专用工作面，已生成受约束 render spec。",
        )

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
        payload = self._serialize_deadline(item)
        payload = self._attach_client_name(payload, session)
        if "days_remaining" not in payload:
            payload["days_remaining"] = self._days_remaining(payload["due_date"], session["today"])
        return payload

    def _enrich_deadline_item(self, item: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        payload = self._serialize_deadline(item)
        if not payload.get("deadline_id") or not payload.get("client_id") or not payload.get("due_date"):
            raise ValueError(f"deadline item missing required fields: {payload}")
        payload = self._attach_client_name(payload, session)
        payload["days_remaining"] = self._days_remaining(payload["due_date"], session["today"])
        payload["available_actions"] = self.engine.available_deadline_actions(session["tenant_id"], payload["deadline_id"])["available_actions"]
        return payload

    def _attach_client_name(self, item: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        if payload.get("client_name"):
            return payload
        client = self._client_map(session["tenant_id"]).get(payload.get("client_id"))
        if client:
            payload["client_name"] = client["name"]
        return payload

    def _extract_deadline_items(self, final_data: Any) -> list[Any]:
        if isinstance(final_data, dict):
            for key in ("deadlines", "items", "results"):
                value = final_data.get(key)
                if isinstance(value, list):
                    return [item for item in value if self._looks_like_deadline(item)]
            if self._looks_like_deadline(final_data):
                return [final_data]
            return []
        if isinstance(final_data, list):
            return [item for item in final_data if self._looks_like_deadline(item)]
        if self._looks_like_deadline(final_data):
            return [final_data]
        return []

    def _extract_bundled_client(self, final_data: Any) -> dict[str, Any] | None:
        if not isinstance(final_data, dict):
            return None
        client = final_data.get("client")
        if client is None:
            return None
        return self._serialize_client(client)

    def _looks_like_deadline(self, item: Any) -> bool:
        if isinstance(item, dict):
            return bool(item.get("deadline_id") and item.get("client_id"))
        return hasattr(item, "deadline_id") and hasattr(item, "client_id")

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

    def _to_selectable(
        self,
        index: int,
        item: dict[str, Any],
        client_name: str | None = None,
        tenant_id: str | None = None,
        session: dict[str, Any] | None = None,
        prefetch_client: bool = False,
    ) -> dict[str, Any]:
        resolved_tenant_id = tenant_id or item.get("tenant_id")
        action = {
            "type": "direct_execute",
            "expected_view": "ClientCard",
            "plan": {
                "plan": [
                    {
                        "step_id": "s1",
                        "type": "cli_call",
                        "cli_group": "deadline",
                        "cli_command": "list",
                        "args": {"tenant_id": resolved_tenant_id, "client_id": item["client_id"]},
                    }
                ],
                "intent_label": "client_deadline_list",
                "op_class": "read",
            },
        }
        if prefetch_client and session and resolved_tenant_id:
            prefetched = self._prefetch_client_workspace(resolved_tenant_id, item["client_id"], session)
            action.update(prefetched)
        return {
            "ref": f"item_{index}",
            "deadline_id": item["deadline_id"],
            "client_id": item["client_id"],
            "client_name": client_name or item.get("client_name"),
            "action": action,
        }

    def _prefetch_client_workspace(self, tenant_id: str, client_id: str, session: dict[str, Any]) -> dict[str, Any]:
        deadline_items = [self._serialize_deadline(item) for item in self.engine.list_deadlines(tenant_id, client_id)]
        enriched_deadlines = [self._enrich_deadline_item(item, session) for item in deadline_items]
        enriched_deadlines.sort(key=lambda item: (item["due_date"], item["deadline_id"]))
        client = self._client_map(tenant_id).get(client_id)
        client_name = client["name"] if client else (enriched_deadlines[0].get("client_name") if enriched_deadlines else client_id)
        selectable_items = [
            self._to_selectable(index, item, client_name=client_name, tenant_id=tenant_id)
            for index, item in enumerate(enriched_deadlines, start=1)
        ]
        view_data = {
            "client_id": client_id,
            "client_name": client_name,
            "entity_type": client["entity_type"] if client else None,
            "registered_states": client["registered_states"] if client else [],
            "deadlines": enriched_deadlines,
        }
        view = {"type": "ClientCard", "data": view_data, "selectable_items": selectable_items}
        snapshot = workspace_snapshot(view, f"预取 {client_name} 的客户工作区。")
        return {
            "prefetch_key": snapshot["key"] if snapshot else f"ClientWorkspace:{client_id}",
            "view_data": view_data,
            "selectable_items": selectable_items,
            "workspace": snapshot,
        }

    def _remember_prefetch_pool(self, session: dict[str, Any], selectable_items: list[dict[str, Any]]) -> None:
        pool = dict(session.get("prefetch_pool") or {})
        for item in selectable_items:
            action = item.get("action") if isinstance(item.get("action"), dict) else {}
            prefetch_key = action.get("prefetch_key")
            if not prefetch_key:
                continue
            pool[prefetch_key] = {
                "view": {
                    "type": action.get("expected_view"),
                    "data": action.get("view_data") or {},
                    "selectable_items": action.get("selectable_items") or [],
                },
                "workspace": action.get("workspace"),
            }
        session["prefetch_pool"] = pool

    def _days_remaining(self, due_date: str, today_value: str) -> int:
        due = date.fromisoformat(due_date)
        today = date.fromisoformat(today_value)
        return (due - today).days

    def _truncate(self, text: str, max_chars: int = 50) -> str:
        return text if len(text) <= max_chars else f"{text[: max_chars - 1]}…"
