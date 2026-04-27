from __future__ import annotations

from typing import Any


WORKSPACE_REGISTRY: dict[str, dict[str, Any]] = {
    "TodayQueue": {
        "purpose": "优先级判断",
        "primary_intent": "导航",
        "description": "Sarah 的今日待办，用于决定先处理哪个",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["prioritize", "filter", "compare"],
        "prefetch_targets": ["ClientWorkspace"],
    },
    "ClientWorkspace": {
        "purpose": "客户合规管理",
        "primary_intent": "操作",
        "description": "单个客户的合规状态，用于处理具体 deadline",
        "editable_fields": ["due_date", "notes"],
        "available_actions": ["complete", "snooze", "waive", "override"],
        "context_actions": ["view_history", "view_rule", "draft_message"],
        "prefetch_targets": ["AuditWorkspace", "TodayQueue"],
    },
    "AuditWorkspace": {
        "purpose": "审计追溯",
        "primary_intent": "查阅",
        "description": "查看 deadline 的变更历史，不支持修改",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["explain_change", "back_to_client"],
        "prefetch_targets": ["ClientWorkspace"],
    },
    "PrioritizeWorkspace": {
        "purpose": "优先级推荐",
        "primary_intent": "决策",
        "description": "Agent 推荐的处理顺序",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["start_with_first", "adjust_priority"],
        "prefetch_targets": ["ClientWorkspace"],
    },
    "ConfirmWorkspace": {
        "purpose": "写操作确认",
        "primary_intent": "确认",
        "description": "确认一个写操作，防止误操作",
        "editable_fields": [],
        "available_actions": ["confirm", "cancel"],
        "context_actions": [],
        "prefetch_targets": [],
    },
    "GuidanceWorkspace": {
        "purpose": "意图澄清",
        "primary_intent": "引导",
        "description": "系统无法确定意图，请用户选择",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["option_select"],
        "prefetch_targets": [],
    },
    "GeneratedWorkspace": {
        "purpose": "按需生成工作面",
        "primary_intent": "决策",
        "description": "为没有专用视图的需求生成受约束工作面",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["clarify", "follow_up"],
        "prefetch_targets": [],
    },
    "TaxChangeRadarWorkspace": {
        "purpose": "税务变化监控",
        "primary_intent": "监控",
        "description": "查看内部规则、notice 和近期 deadline 中可能影响客户工作的变化信号",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["review_rules", "inspect_deadlines", "explain_impact"],
        "prefetch_targets": ["ReviewQueueWorkspace", "TodayQueue"],
    },
}


WORKSPACE_BY_VIEW = {
    "ListCard": "TodayQueue",
    "ClientCard": "ClientWorkspace",
    "HistoryCard": "AuditWorkspace",
    "ConfirmCard": "ConfirmWorkspace",
    "GuidanceCard": "GuidanceWorkspace",
    "TaxChangeRadarCard": "TaxChangeRadarWorkspace",
    "RenderSpecSurface": "GeneratedWorkspace",
    "ReminderPreviewCard": "ReminderPreviewWorkspace",
    "ClientListCard": "ClientDirectoryWorkspace",
    "ReviewQueueCard": "ReviewQueueWorkspace",
}


def get_workspace_spec(workspace_type: str | None) -> dict[str, Any]:
    if not workspace_type:
        return {}
    return WORKSPACE_REGISTRY.get(workspace_type, {})


def workspace_allows_edits(workspace_type: str | None) -> bool:
    spec = get_workspace_spec(workspace_type)
    return bool(spec.get("editable_fields"))


def workspace_registry_prompt() -> list[dict[str, Any]]:
    return [
        {
            "type": key,
            "purpose": value["purpose"],
            "description": value["description"],
            "editable_fields": value["editable_fields"],
            "available_actions": value["available_actions"],
        }
        for key, value in WORKSPACE_REGISTRY.items()
    ]
