from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .workspace_registry import WORKSPACE_BY_VIEW


def initialize_system_state(session: dict[str, Any]) -> dict[str, Any]:
    """Ensure the session carries the minimal SystemState-compatible fields."""
    session.setdefault("history_window", [])
    session.setdefault("selectable_items", [])
    session.setdefault("current_view", None)
    session.setdefault("current_actions", [])
    session.setdefault("current_workspace", None)
    session.setdefault("previous_workspace", None)
    session.setdefault("breadcrumb", [])
    session.setdefault("operation_log", [])
    session.setdefault("prefetch_pool", {})
    return session


def remember_response_state(session: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Update workspace/navigation state from a backend response.

    This is the current incremental version of the architecture document's
    SystemState.apply_operation: it keeps one authoritative session snapshot and
    lets the conversation/workspace surfaces render from that same state.
    """
    initialize_system_state(session)
    view = response.get("view") or {}
    previous_workspace = session.get("current_workspace")
    next_workspace = workspace_snapshot(view, response.get("state_summary"))

    if next_workspace and (not previous_workspace or previous_workspace.get("key") != next_workspace.get("key")):
        session["previous_workspace"] = previous_workspace
        session["current_workspace"] = next_workspace
        breadcrumb = list(session.get("breadcrumb") or [])
        workspace_type = next_workspace["type"]
        if not breadcrumb or breadcrumb[-1] != workspace_type:
            breadcrumb.append(workspace_type)
        session["breadcrumb"] = breadcrumb[-8:]
    elif next_workspace:
        session["current_workspace"] = next_workspace

    session["current_view"] = view
    session["selectable_items"] = view.get("selectable_items", [])
    session["current_actions"] = response.get("actions", [])
    session["state_summary"] = response.get("state_summary")
    return session


def record_operation(
    session: dict[str, Any],
    *,
    user_input: str,
    intent_label: str | None,
    op_class: str | None,
    plan_source: str | None,
    view_type: str | None,
) -> dict[str, Any]:
    initialize_system_state(session)
    operation_index = len(session.get("operation_log") or []) + 1
    operation = {
        "operation_id": f"op_{operation_index}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_input": user_input,
        "intent_label": intent_label,
        "op_class": op_class,
        "plan_source": plan_source,
        "view_type": view_type,
        "workspace_ref": (session.get("current_workspace") or {}).get("key"),
    }
    operation_log = list(session.get("operation_log") or [])
    operation_log.append(operation)
    session["operation_log"] = operation_log[-50:]
    return operation


def workspace_snapshot(view: dict[str, Any], state_summary: str | None = None) -> dict[str, Any] | None:
    if not isinstance(view, dict) or not view.get("type"):
        return None
    view_type = str(view["type"])
    workspace_type = WORKSPACE_BY_VIEW.get(view_type, f"{view_type}Workspace")
    data = view.get("data") if isinstance(view.get("data"), dict) else {}
    semantic_id = _semantic_id(view_type, data)
    return {
        "key": f"{workspace_type}:{semantic_id or 'default'}",
        "type": workspace_type,
        "view_type": view_type,
        "semantic_id": semantic_id,
        "title": _workspace_title(view_type, data),
        "summary": state_summary,
        "selectable_count": len(view.get("selectable_items") or []),
    }


def _semantic_id(view_type: str, data: dict[str, Any]) -> str | None:
    if view_type == "ClientCard":
        return str(data.get("client_id") or data.get("client_name") or "")
    if view_type == "HistoryCard":
        return str(data.get("deadline_id") or data.get("client_name") or "")
    if view_type == "ConfirmCard":
        return str(data.get("description") or "")
    if view_type == "RenderSpecSurface":
        spec = data.get("render_spec") if isinstance(data.get("render_spec"), dict) else {}
        return str(spec.get("title") or "")
    if view_type == "TaxChangeRadarCard":
        return str(data.get("title") or view_type)
    if view_type in {"ListCard", "ClientListCard", "ReviewQueueCard", "ReminderPreviewCard"}:
        return str(data.get("title") or data.get("headline") or view_type)
    if view_type == "GuidanceCard":
        return "guidance"
    return view_type


def _workspace_title(view_type: str, data: dict[str, Any]) -> str | None:
    if view_type == "ClientCard":
        return data.get("client_name")
    if view_type == "HistoryCard":
        return data.get("client_name")
    if view_type == "ConfirmCard":
        return data.get("description")
    if view_type == "RenderSpecSurface":
        spec = data.get("render_spec") if isinstance(data.get("render_spec"), dict) else {}
        return spec.get("title")
    if view_type == "TaxChangeRadarCard":
        return data.get("title")
    return data.get("headline") or data.get("title") or data.get("message")
