from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


FieldSource = Literal["user_input", "tool_result", "pending"]
SecretaryActionType = Literal["render", "none"]


@dataclass(slots=True)
class SecretaryField:
    value: Any
    source: FieldSource


@dataclass(slots=True)
class SecretaryWorkspace:
    template: str
    fields: dict[str, SecretaryField]


@dataclass(slots=True)
class SecretaryAction:
    type: SecretaryActionType
    announce: str | None = None
    template: str | None = None
    workspace: SecretaryWorkspace | None = None
    summary: str | None = None
    highlight: list[str] | None = None


@dataclass(slots=True)
class SecretaryEnvelope:
    reply: str
    action: SecretaryAction

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_secretary_envelope(payload: dict[str, Any]) -> SecretaryEnvelope | None:
    """Parse the Claude-first protocol and reject hallucination-prone fields.

    The schema deliberately has no `inferred` source. Unknown sources make the
    envelope invalid so callers can fall back to a chat clarification.
    """
    reply = str(payload.get("reply") or payload.get("chat_response") or "").strip()
    raw_action = payload.get("action")
    if raw_action is None and "mode" in payload:
        raw_action = {"type": "render" if payload.get("mode") == "render" else "none"}
        if isinstance(payload.get("workspace"), dict):
            raw_action["workspace"] = payload["workspace"]
    if not reply or not isinstance(raw_action, dict):
        return None

    action_type = str(raw_action.get("type") or "none")
    if action_type not in {"render", "none"}:
        return None

    if action_type == "none":
        return SecretaryEnvelope(reply=reply, action=SecretaryAction(type="none"))

    raw_workspace = raw_action.get("workspace")
    if not isinstance(raw_workspace, dict):
        raw_workspace = payload.get("workspace")
    if not isinstance(raw_workspace, dict):
        return None

    template = str(raw_action.get("template") or raw_workspace.get("template") or "").strip()
    raw_fields = raw_workspace.get("fields")
    if not template or not isinstance(raw_fields, dict):
        return None

    fields: dict[str, SecretaryField] = {}
    for key, raw_field in raw_fields.items():
        if not isinstance(raw_field, dict):
            return None
        source = str(raw_field.get("source") or "")
        if source not in {"user_input", "tool_result", "pending"}:
            return None
        fields[str(key)] = SecretaryField(value=raw_field.get("value"), source=source)  # type: ignore[arg-type]

    return SecretaryEnvelope(
        reply=reply,
        action=SecretaryAction(
            type="render",
            announce=str(raw_action.get("announce") or "").strip() or None,
            template=template,
            workspace=SecretaryWorkspace(template=template, fields=fields),
            summary=str(raw_action.get("summary") or "").strip() or None,
            highlight=[str(item) for item in raw_action.get("highlight", [])] if isinstance(raw_action.get("highlight"), list) else None,
        ),
    )


def envelope_from_response(response: dict[str, Any]) -> dict[str, Any]:
    view = response.get("view")
    should_render = isinstance(view, dict) and bool(view.get("type")) and view.get("type") != "GuidanceCard"
    action = SecretaryAction(
        type="render" if should_render else "none",
        announce="拿出材料" if should_render else None,
        template=str(view.get("type")) if should_render else None,
        workspace=None,
        summary=_summary_from_view(view) if should_render else None,
        highlight=_highlight_from_view(view) if should_render else None,
    )
    return SecretaryEnvelope(reply=str(response.get("message") or ""), action=action).to_dict()


def _summary_from_view(view: dict[str, Any]) -> str | None:
    data = view.get("data") if isinstance(view.get("data"), dict) else {}
    if view.get("type") == "ClientListCard":
        total = data.get("total") or len(data.get("clients") or [])
        return f"{total} 个客户已经整理好。"
    if view.get("type") == "ListCard":
        items = data.get("items") if isinstance(data.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        if first:
            return f"{len(items)} 项任务，最近一项是 {first.get('client_name') or '当前客户'} 的 {first.get('tax_type') or '截止事项'}。"
        return f"{len(items)} 项任务。"
    if view.get("type") == "TaxChangeRadarCard":
        metrics = data.get("metrics") if isinstance(data.get("metrics"), list) else []
        return "，".join(str(item.get("label", "")) + " " + str(item.get("value", "")) for item in metrics[:3] if isinstance(item, dict)) or None
    if view.get("type") == "RenderSpecSurface":
        spec = data.get("render_spec") if isinstance(data.get("render_spec"), dict) else {}
        return str(spec.get("intent_summary") or spec.get("title") or "").strip() or None
    return None


def _highlight_from_view(view: dict[str, Any]) -> list[str] | None:
    selectable = view.get("selectable_items") if isinstance(view.get("selectable_items"), list) else []
    for item in selectable:
        if not isinstance(item, dict):
            continue
        value = item.get("deadline_id") or item.get("client_id") or item.get("ref")
        if value:
            return [str(value)]
    data = view.get("data") if isinstance(view.get("data"), dict) else {}
    for key, id_key in [("items", "deadline_id"), ("deadlines", "deadline_id"), ("clients", "client_id")]:
        rows = data.get(key)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and rows[0].get(id_key):
            return [str(rows[0][id_key])]
    return None
