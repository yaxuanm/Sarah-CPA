from __future__ import annotations

from typing import Any


WORKSPACE_REGISTRY: dict[str, dict[str, Any]] = {
    "TodayQueue": {
        "purpose": "Priority judgment",
        "primary_intent": "Navigation",
        "description": "Sarah's daily queue for deciding what to handle first",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["prioritize", "filter", "compare"],
        "prefetch_targets": ["ClientWorkspace"],
    },
    "ClientWorkspace": {
        "purpose": "Client compliance management",
        "primary_intent": "Operation",
        "description": "A single client's compliance state for handling concrete deadlines",
        "editable_fields": ["due_date", "notes"],
        "available_actions": ["complete", "snooze", "waive", "override"],
        "context_actions": ["view_history", "view_rule", "draft_message"],
        "prefetch_targets": ["AuditWorkspace", "TodayQueue"],
    },
    "AuditWorkspace": {
        "purpose": "Audit traceability",
        "primary_intent": "Read",
        "description": "Review deadline change history; edits are not supported",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["explain_change", "back_to_client"],
        "prefetch_targets": ["ClientWorkspace"],
    },
    "PrioritizeWorkspace": {
        "purpose": "Priority recommendation",
        "primary_intent": "Decision",
        "description": "Agent-recommended handling order",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["start_with_first", "adjust_priority"],
        "prefetch_targets": ["ClientWorkspace"],
    },
    "ConfirmWorkspace": {
        "purpose": "Write confirmation",
        "primary_intent": "Confirmation",
        "description": "Confirm a write action before any record changes",
        "editable_fields": [],
        "available_actions": ["confirm", "cancel"],
        "context_actions": [],
        "prefetch_targets": [],
    },
    "GuidanceWorkspace": {
        "purpose": "Intent clarification",
        "primary_intent": "Guidance",
        "description": "Ask the user to choose when intent is unclear",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["option_select"],
        "prefetch_targets": [],
    },
    "GeneratedWorkspace": {
        "purpose": "On-demand generated workspace",
        "primary_intent": "Decision",
        "description": "Generate a constrained workspace for requests without a dedicated view",
        "editable_fields": [],
        "available_actions": [],
        "context_actions": ["clarify", "follow_up"],
        "prefetch_targets": [],
    },
    "TaxChangeRadarWorkspace": {
        "purpose": "Tax change monitoring",
        "primary_intent": "Monitoring",
        "description": "Review change signals from internal rules, notices, and upcoming deadlines that may affect client work",
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
