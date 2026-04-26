from __future__ import annotations

import re
from typing import Any

from .engine import InfrastructureEngine


class RuleBasedIntentPlanner:
    """Temporary planner for the backend MVP.

    This class deliberately mirrors the future NLU boundary: user text and
    session context go in, Plan JSON comes out.
    """

    def __init__(self, engine: InfrastructureEngine) -> None:
        self.engine = engine

    def plan(self, text: str, session: dict[str, Any]) -> dict[str, Any]:
        tenant_id = session.get("tenant_id")
        if not tenant_id:
            return {
                "special": "reference_unresolvable",
                "message": "需要先指定 tenant，才能读取或更新任务。",
                "options": ["查看今天的待处理事项"],
            }

        lowered = text.casefold()

        if self._looks_like_rule_review(lowered):
            return self._rule_review_plan()

        if self._looks_like_history(lowered):
            target = self._selected_deadline(lowered, session)
            if not target:
                client = self._match_client(tenant_id, lowered)
                if client:
                    return self._client_deadline_plan(tenant_id, client.client_id)
            if not target:
                return {
                    "special": "reference_unresolvable",
                    "intent_label": "deadline_history",
                    "message": "要看变更原因，需要先选中一条任务，或者直接说客户名称。",
                    "options": ["查看今天的待处理事项"],
                    "selectable_items": session.get("selectable_items", []),
                }
            return self._deadline_history_plan(tenant_id, target["deadline_id"])

        if self._looks_like_defer(lowered):
            return {
                "special": "reference_unresolvable",
                "intent_label": "defer",
                "message": "好的，当前任务不做更改。",
                "options": ["查看今天的待处理事项", "继续看当前客户"],
                "selectable_items": session.get("selectable_items", []),
            }

        if self._looks_like_completed(lowered) and not (
            self._looks_like_write(lowered) and not self._looks_like_completed_list_request(lowered)
        ):
            return self._completed_deadlines_plan(tenant_id)

        if self._looks_like_write(lowered) and not self._has_negated_write(lowered) and not self._looks_like_completed_list_request(lowered):
            target = self._selected_deadline(lowered, session)
            if not target:
                return {
                    "special": "reference_unresolvable",
                    "intent_label": "deadline_action_complete",
                    "message": "我还不知道你要更新哪一项。先打开一项任务，或说“完成第一条”。",
                    "options": ["查看今天的待处理事项"],
                    "selectable_items": session.get("selectable_items", []),
                }
            return self._deadline_action_plan(tenant_id, target["deadline_id"], "complete")

        client = self._match_client(tenant_id, lowered)
        if client:
            return self._client_deadline_plan(tenant_id, client.client_id)

        if self._has_negated_write(lowered):
            return {
                "special": "reference_unresolvable",
                "intent_label": "defer",
                "message": "好的，不会标记完成。",
                "options": ["查看今天的待处理事项", "继续看当前客户"],
                "selectable_items": session.get("selectable_items", []),
            }

        if self._looks_like_help(lowered):
            return {
                "special": "reference_unresolvable",
                "intent_label": "help",
                "message": "你可以直接问今天先做什么、查看某个客户、完成当前任务，或追问为什么。",
                "options": ["今天先做什么", "看第一条", "完成当前任务"],
                "selectable_items": session.get("selectable_items", []),
            }

        if self._looks_like_ad_hoc_generation(lowered):
            return {
                "special": "render_spec_needed",
                "intent_label": "ad_hoc_render_spec",
                "message": "我会根据这个需求生成一个临时工作面，而不是回到通用面板。",
                "user_input": text,
                "selectable_items": session.get("selectable_items", []),
            }

        if self._looks_like_notifications(lowered):
            return self._notification_preview_plan(tenant_id)

        if self._looks_like_today(lowered):
            return self._today_plan(tenant_id)

        if self._looks_like_upcoming(lowered):
            return self._upcoming_deadlines_plan(tenant_id)

        if self._looks_like_client_list(lowered):
            return self._client_list_plan(tenant_id)

        target = self._selected_deadline(lowered, session)
        if target and self._looks_like_focus(lowered):
            return self._client_deadline_plan(tenant_id, target["client_id"])

        return {
            "special": "render_spec_needed",
            "intent_label": "ad_hoc_render_spec",
            "message": "我会根据这个需求生成一个临时工作面，而不是回到通用面板。",
            "user_input": text,
            "selectable_items": session.get("selectable_items", []),
        }

    def is_confirm(self, text: str) -> bool:
        lowered = text.casefold()
        return lowered in {"确认", "可以", "对", "yes", "y", "confirm", "ok", "okay"} or "确认" in lowered

    def is_cancel(self, text: str) -> bool:
        lowered = text.casefold()
        return lowered in {"取消", "算了", "不用", "no", "n", "cancel"} or "取消" in lowered

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

    def _upcoming_deadlines_plan(self, tenant_id: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "list",
                    "args": {"tenant_id": tenant_id, "status": "pending", "limit": 100},
                }
            ],
            "intent_label": "upcoming_deadlines",
            "op_class": "read",
        }

    def _completed_deadlines_plan(self, tenant_id: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "list",
                    "args": {"tenant_id": tenant_id, "status": "completed", "limit": 50},
                }
            ],
            "intent_label": "completed_deadlines",
            "op_class": "read",
        }

    def _notification_preview_plan(self, tenant_id: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "notify",
                    "cli_command": "preview",
                    "args": {"tenant_id": tenant_id, "within_days": 7},
                }
            ],
            "intent_label": "notification_preview",
            "op_class": "read",
        }

    def _rule_review_plan(self) -> dict[str, Any]:
        return {
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
        }

    def _client_list_plan(self, tenant_id: str) -> dict[str, Any]:
        return {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "client",
                    "cli_command": "list",
                    "args": {"tenant_id": tenant_id},
                }
            ],
            "intent_label": "client_list",
            "op_class": "read",
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
            "intent_label": f"deadline_action_{action}",
            "op_class": "write",
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

    def _match_client(self, tenant_id: str, lowered_text: str):
        candidates = []
        for client in self.engine.list_clients(tenant_id):
            name = client.name.casefold()
            compact_name = name.replace(" llc", "").replace(" inc", "").replace(" corp", "")
            tokens = [token for token in compact_name.replace("-", " ").split() if len(token) > 2]
            token_hits = sum(1 for token in tokens if token in lowered_text)
            if name in lowered_text or compact_name in lowered_text or token_hits >= min(2, len(tokens)):
                candidates.append(client)
        return candidates[0] if len(candidates) == 1 else None

    def _selected_deadline(self, lowered_text: str, session: dict[str, Any]) -> dict[str, Any] | None:
        selectable = session.get("selectable_items") or []
        if not selectable:
            return None
        numeric_match = re.search(r"(?:第\s*)?([1-9])\s*(?:条|个|项|item)", lowered_text)
        if not numeric_match:
            numeric_match = re.search(r"item\s*([1-9])", lowered_text)
        if numeric_match:
            index = int(numeric_match.group(1)) - 1
            return selectable[index] if 0 <= index < len(selectable) else None
        if any(token in lowered_text for token in ["第一", "first", "1st", "第一个"]):
            return selectable[0]
        if any(token in lowered_text for token in ["第二", "second", "2nd"]):
            return selectable[1] if len(selectable) > 1 else None
        if any(token in lowered_text for token in ["第三", "third", "3rd"]):
            return selectable[2] if len(selectable) > 2 else None
        if any(token in lowered_text for token in ["这个", "当前", "刚才", "刚刚", "上一条", "current", "this", "that", "it", "它"]):
            return selectable[0]
        return selectable[0] if len(selectable) == 1 else None

    def _looks_like_write(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "完成",
                "已处理",
                "已经处理了",
                "已发送",
                "记为",
                "标记",
                "办完",
                "处理掉",
                "close this",
                "resolve this",
                "complete",
                "done",
                "mark sent",
                "mark as sent",
                "record it",
                "record as handled",
                "record this as handled",
                "record current as handled",
                "sent to client",
                "client replied",
                "mark this as handled",
                "关掉",
                "发给客户",
                "finish this",
                "搞定",
                "已做",
                "check off",
            ]
        )

    def _has_negated_write(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "别标记",
                "不要标记",
                "别完成",
                "不要完成",
                "不要处理",
                "别处理",
                "先别标记",
                "不标记完成",
                "暂时不标记",
                "暂时不标记完成",
                "not mark",
                "don't mark",
                "do not mark",
                "not complete",
                "don't complete",
                "do not complete",
                "don't process",
                "do not process",
            ]
        )

    def _looks_like_defer(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "暂时不做",
                "先不做",
                "先不处理",
                "先别动",
                "先放",
                "先等等",
                "等等",
                "等一下",
                "暂时不处理",
                "稍后",
                "待会",
                "later",
                "not now",
                "skip for now",
                "skip this",
                "暂时跳过",
                "跳过这个",
                "暂时搁置",
                "搁置",
                "leave it",
                "hold off",
                "hold this for now",
                "pause this",
                "leave this alone",
                "hold on",
            ]
        )

    def _looks_like_today(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "今天",
                "today",
                "最紧急",
                "最急",
                "urgent",
                "先做",
                "优先",
                "priority",
                "应该先处理",
                "待处理",
                "todo",
                "to do",
                "what should i do",
                "work queue",
                "top priority",
                "morning list",
                "due today",
                "deadline today",
                "due for",
                "最该盯",
            ]
        )

    def _looks_like_upcoming(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "未来",
                "所有ddl",
                "所有 ddl",
                "ddl",
                "deadline",
                "deadlines",
                "due date",
                "due dates",
                "截止日",
                "截止事项",
                "下个月",
                "接下来",
                "未来30天",
                "30 days",
                "next month",
                "下月",
                "upcoming",
                "coming due",
                "next 30",
                "next week",
                "下周",
                "quarter ahead",
                "this month",
                "month ahead",
            ]
        )

    def _looks_like_completed(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "已完成",
                "完成了哪些",
                "完成记录",
                "已经处理的",
                "已处理的项目",
                "哪些已经处理",
                "已处理的有哪些",
                "什么已经处理",
                "已处理列表",
                "完成列表",
                "任务列表",
                "what items are finished",
                "已处理的列表",
                "已经完成的",
                "处理完成",
                "处理完",
                "what has been handled",
                "handled work",
                "what's done",
                "已经处理完",
                "看完成了什么",
                "已完成的工作",
                "completed",
                "done items",
                "finished",
                "closed",
                "resolved",
            ]
        )

    def _looks_like_notifications(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "通知",
                "提醒",
                "要发哪些邮件",
                "哪些邮件",
                "哪些客户要催",
                "要催哪些",
                "接下来要催谁",
                "notification",
                "reminder",
                "notify",
                "email preview",
                "follow-up emails",
                "pending emails",
                "send reminders",
                "client reminders",
                "follow up",
            ]
        )

    def _looks_like_ad_hoc_generation(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "帮我写",
                "写一封",
                "起草",
                "草稿",
                "话术",
                "措辞",
                "生成",
                "draft",
                "write a",
                "prepare a",
                "wording",
                "message for",
                "email for",
            ]
        )

    def _looks_like_rule_review(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "规则审核",
                "审核队列",
                "低置信",
                "rule review",
                "review queue",
                "low confidence",
                "pending review",
                "pending rules",
                "规则要审核",
                "规则需要审核",
                "有哪些规则需要审核",
                "规则解析",
                "rule parsing",
                "parsing issues",
                "rules needing review",
                "rules need review",
                "review parsed rules",
                "source parsing",
                "needs review",
            ]
        )

    def _looks_like_client_list(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "客户列表",
                "所有客户",
                "有哪些客户",
                "多少个客户",
                "我有多少个客户",
                "客户清单",
                "客户名单",
                "我们的客户有哪些",
                "client list",
                "all clients",
                "list all",
                "show clients",
                "client names",
                "list clients",
                "客户都列出来",
                "clients",
                "client roster",
                "customer list",
                "客户名录",
                "全部客户",
                "customer accounts",
                "customer roster",
            ]
        )

    def _looks_like_focus(self, lowered: str) -> bool:
        return any(token in lowered for token in ["看", "打开", "查看", "先", "focus", "open", "show"])

    def _looks_like_history(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "为什么",
                "历史",
                "变更",
                "来源",
                "怎么来的",
                "什么时候改",
                "什么时候加",
                "audit trail",
                "audit",
                "who touched",
                "who modified",
                "谁改",
                "why blocked",
                "why",
                "history",
                "changed",
                "modified",
                "change log",
                "source",
            ]
        )

    def _looks_like_help(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "帮助",
                "怎么用",
                "怎样使用",
                "how do i use",
                "怎么操作",
                "能干嘛",
                "能做什么",
                "能帮我做什么",
                "你能帮什么",
                "有什么功能",
                "支持什么功能",
                "what do you do",
                "what do you support",
                "show me what's available",
                "available commands",
                "show me available commands",
                "show commands",
                "支持哪些操作",
                "有哪些命令",
                "commands",
                "available operations",
                "operations are supported",
                "what commands",
                "help",
                "what can you do",
                "what you can do",
            ]
        )

    def _looks_like_completed_list_request(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in [
                "已处理列表",
                "已处理的列表",
                "完成记录",
                "处理完成",
                "已经处理的",
                "已处理的项目",
                "什么已经处理",
                "哪些已经处理",
                "列表",
                "任务列表",
                "list",
                "items",
                "what work",
                "what's done",
                "which items",
                "what items",
                "处理完",
                "完成了什么",
                "已完成的工作",
                "completed",
                "already completed",
                "deadlines",
                "已经完成的",
                "哪些",
                "有哪些",
            ]
        )
