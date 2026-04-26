from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class IntentMatch:
    template: "IntentTemplate"
    similarity: float
    plan: dict[str, Any]


@dataclass(slots=True)
class IntentTemplate:
    intent_id: str
    intent_label: str
    example_inputs: list[str]
    canonical_plan: dict[str, Any]
    view_type: str
    vector: dict[str, float]
    hit_count: int = 0
    success_rate: float = 1.0
    status: str = "active"
    correction_count: int = 0
    missing_info_count: int = 0
    missing_info_inputs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class InMemoryIntentLibrary:
    """MVP intent cache.

    This uses deterministic lexical features so the flywheel can be tested
    without model calls. The storage and matcher are intentionally swappable.
    """

    def __init__(self, *, match_threshold: float = 0.62) -> None:
        self.match_threshold = match_threshold
        self._templates: list[IntentTemplate] = []
        self._feedback_events: list[dict[str, Any]] = []

    def all(self) -> list[IntentTemplate]:
        return list(self._templates)

    def find_by_id(self, intent_id: str) -> IntentTemplate | None:
        return next((template for template in self._templates if template.intent_id == intent_id), None)

    def match(self, user_input: str, session: dict[str, Any]) -> IntentMatch | None:
        if not self._templates:
            return None

        vector = self._vectorize(user_input, session)
        candidates = [
            (template, self._template_similarity(vector, template))
            for template in self._templates
            if template.status == "active"
        ]
        if not candidates:
            return None

        template, similarity = max(candidates, key=lambda item: item[1])
        if similarity < self.match_threshold:
            return None

        template.hit_count += 1
        template.updated_at = datetime.now(timezone.utc)
        return IntentMatch(
            template=template,
            similarity=similarity,
            plan=self._instantiate_plan(template.canonical_plan, session),
        )

    def learn(self, user_input: str, plan: dict[str, Any], session: dict[str, Any], view_type: str | None = None) -> IntentTemplate:
        intent_label = plan.get("intent_label", "unknown")
        existing = next((template for template in self._templates if template.intent_label == intent_label), None)
        if existing:
            existing.example_inputs.append(user_input)
            existing.vector = self._average_vector(existing.example_inputs)
            existing.updated_at = datetime.now(timezone.utc)
            return existing

        template = IntentTemplate(
            intent_id=f"intent-{uuid4()}",
            intent_label=intent_label,
            example_inputs=[user_input],
            canonical_plan=self._abstract_plan(plan, session),
            view_type=view_type or self._default_view_type(intent_label),
            vector=self._vectorize(user_input, session),
        )
        self._templates.append(template)
        return template

    def record_feedback(
        self,
        intent_id: str,
        *,
        is_correction: bool,
        user_input: str | None = None,
        reason: str | None = None,
    ) -> None:
        template = next(template for template in self._templates if template.intent_id == intent_id)
        if is_correction:
            template.success_rate *= 0.95
            template.correction_count += 1
            signal = "correction"
        else:
            template.success_rate = min(1.0, template.success_rate * 1.02)
            signal = "success"
        if template.success_rate < 0.70:
            template.status = "review_needed"
        template.updated_at = datetime.now(timezone.utc)
        self._feedback_events.append(
            {
                "signal": signal,
                "intent_id": intent_id,
                "intent_label": template.intent_label,
                "user_input": user_input,
                "reason": reason,
                "created_at": template.updated_at.isoformat(),
            }
        )

    def record_missing_field(self, intent_label: str, user_input: str, reason: str | None = None) -> IntentTemplate | None:
        template = next((template for template in self._templates if template.intent_label == intent_label), None)
        if not template:
            return None
        template.missing_info_count += 1
        template.missing_info_inputs.append(user_input)
        del template.missing_info_inputs[:-20]
        template.updated_at = datetime.now(timezone.utc)
        self._feedback_events.append(
            {
                "signal": "missing_info",
                "intent_id": template.intent_id,
                "intent_label": template.intent_label,
                "user_input": user_input,
                "reason": reason,
                "created_at": template.updated_at.isoformat(),
            }
        )
        return template

    def stats(self) -> dict[str, Any]:
        templates = self.all()
        return {
            "template_count": len(templates),
            "active_templates": len([template for template in templates if template.status == "active"]),
            "review_needed_templates": len([template for template in templates if template.status == "review_needed"]),
            "feedback_events": len(self._feedback_events),
            "corrections": len([event for event in self._feedback_events if event["signal"] == "correction"]),
            "missing_info_events": len([event for event in self._feedback_events if event["signal"] == "missing_info"]),
        }

    def feedback_events(self, *, signal: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        events = [event for event in self._feedback_events if signal is None or event["signal"] == signal]
        return list(reversed(events[-limit:]))

    def review_queue(self, *, limit: int = 50) -> list[dict[str, Any]]:
        template_items = [
            {
                "intent_id": template.intent_id,
                "intent_label": template.intent_label,
                "status": template.status,
                "success_rate": template.success_rate,
                "correction_count": template.correction_count,
                "missing_info_count": template.missing_info_count,
                "updated_at": template.updated_at.isoformat(),
            }
            for template in self._templates
            if template.status == "review_needed" or template.correction_count > 0
        ]
        return sorted(template_items, key=lambda item: item["updated_at"], reverse=True)[:limit]

    def _abstract_plan(self, plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        tenant_id = session.get("tenant_id")
        selectable_items = session.get("selectable_items") or []
        deadline_ids = {item.get("deadline_id") for item in selectable_items}
        client_ids = {item.get("client_id") for item in selectable_items}

        def replace(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            if value == tenant_id:
                return "$tenant_id"
            if value in deadline_ids:
                return "$selected.deadline_id"
            if value in client_ids:
                return "$selected.client_id"
            return value

        return replace(plan)

    def _instantiate_plan(self, canonical_plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        selected = (session.get("selectable_items") or [{}])[0]

        def replace(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            if value == "$tenant_id":
                return session["tenant_id"]
            if value == "$selected.deadline_id":
                return selected["deadline_id"]
            if value == "$selected.client_id":
                return selected["client_id"]
            return value

        return replace(canonical_plan)

    def _average_vector(self, inputs: list[str]) -> dict[str, float]:
        merged: dict[str, float] = {}
        for text in inputs:
            for token, weight in self._vectorize(text).items():
                merged[token] = merged.get(token, 0.0) + weight
        return {token: weight / len(inputs) for token, weight in merged.items()}

    def _vectorize(self, text: str, session: dict[str, Any] | None = None) -> dict[str, float]:
        normalized = text.casefold()
        tokens: dict[str, float] = {}

        for token in self._semantic_tokens(normalized):
            tokens[token] = tokens.get(token, 0.0) + 2.0

        for client_name in (session or {}).get("client_names", []):
            name = str(client_name).casefold()
            compact = (
                name.replace(" llc", "")
                .replace(" inc", "")
                .replace(" corp", "")
                .replace(" company", "")
                .replace(" consulting", "")
            )
            if name and (name in normalized or compact in normalized):
                tokens["intent:client_deadline"] = tokens.get("intent:client_deadline", 0.0) + 2.5

        word = []
        for char in normalized:
            if char.isalnum():
                word.append(char)
            else:
                if word:
                    token = "".join(word)
                    tokens[token] = tokens.get(token, 0.0) + 1.0
                    word = []
        if word:
            token = "".join(word)
            tokens[token] = tokens.get(token, 0.0) + 1.0

        cjk_chars = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
        for index in range(len(cjk_chars) - 1):
            token = "".join(cjk_chars[index : index + 2])
            tokens[token] = tokens.get(token, 0.0) + 0.4

        return tokens

    def _semantic_tokens(self, normalized: str) -> list[str]:
        tokens = []
        has_completed_list_request = any(
            item in normalized
            for item in [
                "已处理列表",
                "已处理的列表",
                "完成记录",
                "处理完成",
                "已经处理的",
                "已处理的项目",
                "什么已经处理",
                "哪些已经处理",
                "列表",
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
        has_negated_write = any(
            item in normalized
            for item in [
                "别标记",
                "不要标记",
                "先不要标记",
                "先别标记",
                "别完成",
                "不要完成",
                "不要处理",
                "别处理",
                "不标记完成",
                "暂时不标记",
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
        has_write_request = not has_negated_write and not has_completed_list_request and any(
            item in normalized
            for item in [
                "完成",
                "已处理",
                "已经处理了",
                "已发送",
                "记为",
                "标记",
                "办完",
                "处理掉",
                "complete",
                "done",
                "mark sent",
                "mark as sent",
                "record it",
                "record as sent",
                "record as handled",
                "record this as handled",
                "record current as handled",
                "close this",
                "resolve this",
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
        if any(
            item in normalized
            for item in [
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
        ):
            tokens.append("intent:today")
        if any(
            item in normalized
            for item in [
                "acme",
                "techcorp",
                "greenway",
                "brighton",
                "baker",
                "techvision",
                " corp",
                " llc",
                " associates",
            ]
        ):
            tokens.append("intent:client_deadline")
        if any(item in normalized for item in ["看", "打开", "查看", "focus", "open", "show"]):
            tokens.append("intent:focus")
        if has_write_request:
            tokens.append("intent:write")
        if has_negated_write:
            tokens.append("intent:defer")
        if any(
            item in normalized
            for item in [
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
        ):
            tokens.append("intent:history")
        if any(
            item in normalized
            for item in [
                "暂时不做",
                "先不做",
                "先不处理",
                "先别动",
                "先放",
                "先等等",
                "等等",
                "暂时不要处理",
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
        ):
            tokens.append("intent:defer")
        if any(
            item in normalized
            for item in [
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
        ):
            tokens.append("intent:help")
        if any(
            item in normalized
            for item in [
                "未来",
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
        ):
            tokens.append("intent:upcoming")
        if not has_write_request and any(
            item in normalized
            for item in [
                "已完成",
                "完成记录",
                "已经处理的",
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
                "completed",
                "done items",
                "finished",
                "closed",
                "resolved",
            ]
        ):
            tokens.append("intent:completed")
        if any(
            item in normalized
            for item in [
                "通知",
                "提醒",
                "催",
                "邮件",
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
        ):
            tokens.append("intent:notification")
        if any(
            item in normalized
            for item in [
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
        ):
            tokens.append("intent:rule_review")
        if any(
            item in normalized
            for item in [
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
        ):
            tokens.append("intent:client_list")
        return tokens

    def _similarity(self, left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(weight * right.get(token, 0.0) for token, weight in left.items())
        left_norm = sum(weight * weight for weight in left.values()) ** 0.5
        right_norm = sum(weight * weight for weight in right.values()) ** 0.5
        return dot / (left_norm * right_norm)

    def _template_similarity(self, vector: dict[str, float], template: IntentTemplate) -> float:
        similarities = [self._similarity(vector, template.vector)]
        similarities.extend(self._similarity(vector, self._vectorize(example)) for example in template.example_inputs)
        return max(similarities)

    def _default_view_type(self, intent_label: str) -> str:
        return {
            "today": "ListCard",
            "client_deadline_list": "ClientCard",
            "deadline_history": "GuidanceCard",
            "defer": "GuidanceCard",
            "help": "GuidanceCard",
            "upcoming_deadlines": "GuidanceCard",
            "completed_deadlines": "GuidanceCard",
            "notification_preview": "GuidanceCard",
            "rule_review": "GuidanceCard",
            "client_list": "GuidanceCard",
        }.get(intent_label, "ConfirmCard" if intent_label.startswith("deadline_action_") else "GuidanceCard")
