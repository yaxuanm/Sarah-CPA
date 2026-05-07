from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .app import create_app
from .core.ai_assistants import (
    AIAssistantError,
    draft_client_followup,
    fallback_client_followup,
    fallback_import_mapping,
    propose_import_mapping,
)
from .core.models import NotificationChannel
from .core.notifiers import ConsoleNotifier, NotifierRegistry
from .core.secretary_envelope import envelope_from_response
from .core.system_state import record_operation, remember_response_state


@dataclass(slots=True)
class ChatRequest:
    user_input: str
    tenant_id: str
    session: dict[str, Any] | None = None
    session_id: str | None = None
    today: str | None = None


def create_fastapi_app(db_path: str | None = None):
    try:
        from fastapi import Body, FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import StreamingResponse
    except ImportError as exc:  # pragma: no cover - optional dependency guard.
        raise RuntimeError("FastAPI support requires installing duedatehq[api].") from exc

    app_state = create_app(db_path)
    api = FastAPI(title="DueDateHQ API")
    api.state.app_state = app_state
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
            "http://127.0.0.1:5182",
            "http://localhost:5182",
            "http://127.0.0.1:5183",
            "http://localhost:5183",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.post("/chat")
    def chat(body: dict[str, Any] = Body(...)):
        session = _prepare_session(body)
        response = app_state.interaction_backend.process_message(body["user_input"], session)
        return {"response": response, "session": session}

    @api.post("/bootstrap/today")
    def bootstrap_today(body: dict[str, Any] = Body(...)):
        session = _prepare_session(body)
        response = app_state.interaction_backend.process_plan(_today_plan(session["tenant_id"]), session)
        _remember_bootstrap_response(session, response)
        return {"response": {"status": "ok", **response, "session_id": session.get("session_id")}, "session": session}

    @api.post("/action")
    def action(body: dict[str, Any] = Body(...)):
        session = _prepare_session(body)
        action_payload = body.get("action") if isinstance(body.get("action"), dict) else {}
        command = action_payload.get("command")
        if isinstance(command, str):
            response = app_state.interaction_backend.process_direct_command(command, session)
            return {"response": response, "session": session}
        plan = body.get("plan") or action_payload.get("plan")
        if not isinstance(plan, dict):
            return {
                "response": {
                    "status": "error",
                    "message": "This button is missing an executable plan. No data was changed.",
                    "view": session.get("current_view"),
                    "actions": session.get("current_actions", []),
                    "session_id": session.get("session_id"),
                },
                "session": session,
            }
        response = app_state.interaction_backend.process_direct_action(plan, session)
        return {"response": response, "session": session}

    @api.post("/sources/sync")
    def sync_sources(body: dict[str, Any] = Body(default={})):
        fetched_at = _parse_datetime(body.get("fetched_at"))
        results = app_state.engine.sync_official_sources(
            sources=body.get("sources") if isinstance(body.get("sources"), list) else None,
            states=body.get("states") if isinstance(body.get("states"), list) else None,
            all_supported=bool(body.get("all", False)),
            fetched_at=fetched_at,
            actor=str(body.get("actor") or "api"),
        )
        return {"results": _jsonable(results)}

    @api.get("/sources/status")
    def source_status():
        fetch_runs = app_state.engine.list_fetch_runs()
        supported_keys = {"state_ca", "state_tx", "state_ny"}
        latest_by_source: dict[str, Any] = {}
        for run in fetch_runs:
            if run.source_key not in latest_by_source:
                latest_by_source[run.source_key] = run
        sources = [
            {
                **source,
                "sync_supported": source["source_key"] in supported_keys,
                "latest_fetch_run": _jsonable(latest_by_source.get(source["source_key"])),
            }
            for source in app_state.engine.list_sources()
            if source["source_key"] in supported_keys
        ]
        return {"sources": sources}

    @api.post("/dashboard/payload")
    def dashboard_payload(body: dict[str, Any] = Body(...)):
        tenant_id = str(body["tenant_id"])
        limit = int(body.get("limit") or 5)
        return {"payload": _jsonable(app_state.engine.dashboard_payload(tenant_id, limit=limit))}

    @api.post("/notifications/preview")
    def notification_preview(body: dict[str, Any] = Body(...)):
        tenant_id = str(body["tenant_id"])
        within_days = int(body.get("within_days") or 7)
        return {
            "routes": _jsonable(app_state.engine.list_notification_routes(tenant_id)),
            "reminders": _jsonable(app_state.engine.notify_preview(tenant_id, within_days=within_days)),
            "deliveries": _jsonable(app_state.engine.list_notification_deliveries(tenant_id)),
        }

    @api.post("/notifications/send-pending")
    def notification_send_pending(body: dict[str, Any] = Body(...)):
        tenant_id = str(body["tenant_id"])
        if body.get("trigger_due"):
            app_state.engine.trigger_due_reminders(now=_parse_datetime(body.get("at")), tenant_id=tenant_id)
        sent = app_state.engine.dispatch_notification_deliveries(
            tenant_id,
            _console_notifier_registry(),
            actor=str(body.get("actor") or "api"),
        )
        return {
            "sent": sent,
            "deliveries": _jsonable(app_state.engine.list_notification_deliveries(tenant_id)),
        }

    @api.post("/import/preview")
    def import_preview(body: dict[str, Any] = Body(...)):
        path = _write_import_csv(body)
        try:
            preview = app_state.engine.preview_import_csv(path)
            preview["source_name"] = str(body.get("source_name") or preview["source_name"])
            return {"preview": _jsonable(preview)}
        finally:
            path.unlink(missing_ok=True)

    @api.post("/import/apply")
    def import_apply(body: dict[str, Any] = Body(...)):
        tenant_id = str(body["tenant_id"])
        path = _write_import_csv(body)
        try:
            result = app_state.engine.apply_import_csv(
                tenant_id=tenant_id,
                csv_path=path,
                tax_year=int(body.get("tax_year") or 2026),
                default_client_type=str(body.get("default_client_type") or "business"),
                actor=str(body.get("actor") or "api"),
            )
            return {
                "result": {
                    "source_name": str(body.get("source_name") or result["source_name"]),
                    "created_clients": _jsonable(result["created_clients"]),
                    "created_blockers": _jsonable(result["created_blockers"]),
                    "created_tasks": _jsonable(result["created_tasks"]),
                    "skipped_rows": _jsonable(result["skipped_rows"]),
                    "dashboard": _jsonable(result["dashboard"]),
                }
            }
        finally:
            path.unlink(missing_ok=True)

    @api.post("/ai/import-mapping")
    def ai_import_mapping(body: dict[str, Any] = Body(...)):
        prompt = str(body.get("prompt") or "")
        headers = [str(item) for item in body.get("headers", []) if str(item).strip()]
        target_fields = _normalize_import_target_fields(body.get("target_fields"))
        custom_fields = body.get("custom_fields") if isinstance(body.get("custom_fields"), list) else []
        try:
            proposal = propose_import_mapping(
                prompt=prompt,
                headers=headers,
                target_fields=target_fields,
                custom_fields=custom_fields,
            )
        except (AIAssistantError, ValueError, json.JSONDecodeError):
            proposal = fallback_import_mapping(prompt, headers, target_fields)
        return {"proposal": proposal}

    @api.post("/ai/followup-draft")
    def ai_followup_draft(body: dict[str, Any] = Body(...)):
        work_item = body.get("work_item") if isinstance(body.get("work_item"), dict) else {}
        previous_body = str(body.get("previous_body") or "")
        try:
            draft = draft_client_followup(work_item=work_item, previous_body=previous_body)
        except (AIAssistantError, ValueError, json.JSONDecodeError):
            draft = fallback_client_followup(work_item, previous_body)
        return {"draft": draft}

    @api.post("/session/{tenant_id}")
    def start_session(tenant_id: str):
        return app_state.interaction_sessions.start(tenant_id)

    @api.get("/session/{session_id}")
    def get_session(session_id: str):
        return app_state.interaction_sessions.get(session_id)

    @api.post("/chat/stream")
    def chat_stream(body: dict[str, Any] = Body(...)):
        session = _prepare_session(body)

        def events():
            user_input = body.get("user_input", "")
            yield _sse("agent_step", {"label": "Receive request", "detail": "Reply first, then decide whether to pull supporting material.", "tone": "blue"})
            yield _sse("thinking", {"message": _thinking_status(user_input, session)})
            previous_feedback_count = len(session.get("flywheel_feedback_events", []))
            try:
                response = app_state.interaction_backend.process_message(user_input, session)
            except Exception as exc:  # noqa: BLE001 - keep SSE stream readable during prototype failures.
                response = {
                    "status": "error",
                    "message": f"This request failed: {type(exc).__name__}. No data was changed.",
                    "view": {
                        "type": "GuidanceCard",
                        "data": {
                            "message": "This request failed, but the system did not write any changes. Return to today's queue and try again.",
                            "options": ["View today's queue"],
                            "context_options": session.get("selectable_items", []),
                        },
                        "selectable_items": session.get("selectable_items", []),
                    },
                    "actions": [],
                    "session_id": session.get("session_id"),
                }
                session.setdefault("stream_errors", []).append(
                    {"type": type(exc).__name__, "message": str(exc), "user_input": body.get("user_input")}
                )
            last_turn = session.get("last_turn", {})
            yield _sse(
                "intent_confirmed",
                {
                    "intent_label": last_turn.get("intent_label"),
                    "plan_source": last_turn.get("plan_source"),
                    "template_id": last_turn.get("template_id"),
                },
            )
            secretary = response.get("secretary") if isinstance(response.get("secretary"), dict) else envelope_from_response(response)
            reply = str(secretary.get("reply") or response.get("message") or "")
            for chunk in _message_chunks(reply):
                yield _sse("message_delta", {"delta": chunk})
            action = secretary.get("action") if isinstance(secretary.get("action"), dict) else {}
            if action.get("type") == "render":
                render_template = str(action.get("template") or (response.get("view") or {}).get("type") or "generated_workspace")
                if _needs_template_render_loop(response.get("view"), render_template):
                    yield _sse("agent_step", {"label": "Prepare material", "detail": action.get("announce") or "Pull supporting material", "tone": "gold"})
                    yield _sse(
                        "action_started",
                        {
                            "type": "render",
                            "announce": action.get("announce"),
                            "template": render_template,
                        },
                    )
                    slots = _slots_from_secretary_action(action, session)
                    yield _sse("agent_step", {"label": "resolve_template", "detail": render_template, "tone": "blue"})
                    template_result = app_state.template_tools.run_render_loop(
                        intent=render_template,
                        slots=slots,
                        tenant_id=session["tenant_id"],
                        session=session,
                        response_view=response.get("view") if isinstance(response.get("view"), dict) else None,
                    )
                    resolution = template_result["resolution"]
                    yield _sse(
                        "agent_step",
                        {
                            "label": "fetch_slot_data",
                            "detail": f"{resolution.get('status')}:{resolution.get('template_id') or resolution.get('base_template_id') or resolution.get('staging_template_id')}",
                            "tone": "gold",
                        },
                    )
                    yield _sse("agent_step", {"label": "dispatch_render", "detail": template_result["render_event"]["render_id"], "tone": "green"})
                    yield _sse(
                        "render_event",
                        {
                            **template_result["render_event"],
                            "resolution": resolution,
                            "actions": response.get("actions", []),
                            "summary": action.get("summary"),
                            "highlight": action.get("highlight") if isinstance(action.get("highlight"), list) else [],
                            "cross_reference": {
                                "reply": reply,
                                "summary": action.get("summary"),
                                "highlight": action.get("highlight") if isinstance(action.get("highlight"), list) else [],
                            },
                        },
                    )
                yield _sse("workspace_rendered", {"view": response.get("view"), "actions": response.get("actions", [])})
            yield _sse("view_rendered", {"view": response.get("view"), "actions": response.get("actions", [])})
            new_feedback = _latest_new_feedback_event(session, previous_feedback_count)
            if new_feedback:
                yield _sse("feedback_recorded", new_feedback)
            yield _sse("done", {"response": response, "session": session})

        return StreamingResponse(events(), media_type="text/event-stream")

    @api.get("/flywheel/stats")
    def flywheel_stats():
        return app_state.intent_library.stats()

    return api


def _slots_from_secretary_action(action: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    workspace = action.get("workspace") if isinstance(action.get("workspace"), dict) else {}
    fields = workspace.get("fields") if isinstance(workspace.get("fields"), dict) else {}
    for name, field in fields.items():
        if isinstance(field, dict):
            slots[str(name)] = field.get("value")
    if session.get("current_view"):
        slots.setdefault(
            "current_view_type",
            (session.get("current_view") or {}).get("type") if isinstance(session.get("current_view"), dict) else None,
        )
    return slots


def _needs_template_render_loop(view: Any, render_template: str) -> bool:
    if isinstance(view, dict) and view.get("type") in {
        "ClientCard",
        "ListCard",
        "ConfirmCard",
        "HistoryCard",
        "GuidanceCard",
        "TaxChangeRadarCard",
        "ClientListCard",
        "ReviewQueueCard",
        "ReminderPreviewCard",
    }:
        return False
    return render_template in {"generated_workspace", "RenderSpecSurface"} or (
        isinstance(view, dict) and view.get("type") == "RenderSpecSurface"
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _console_notifier_registry() -> NotifierRegistry:
    return NotifierRegistry(
        {
            NotificationChannel.EMAIL: ConsoleNotifier(NotificationChannel.EMAIL),
            NotificationChannel.SMS: ConsoleNotifier(NotificationChannel.SMS),
            NotificationChannel.SLACK: ConsoleNotifier(NotificationChannel.SLACK),
        }
    )


def _write_import_csv(body: dict[str, Any]) -> Path:
    csv_text = str(body.get("csv_text") or "")
    if not csv_text.strip():
        raise ValueError("csv_text is required")
    source_name = str(body.get("source_name") or "upload.csv")
    suffix = ".csv" if not source_name.lower().endswith(".csv") else ""
    handle = NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        suffix=suffix,
        prefix="duedatehq-import-",
        delete=False,
    )
    with handle:
        handle.write(csv_text)
    return Path(handle.name)


def _normalize_import_target_fields(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [
            {"key": "client_name", "label": "Client name", "aliases": ["client", "name", "business name"]},
            {"key": "entity_type", "label": "Entity type", "aliases": ["entity", "type"]},
            {"key": "operating_states", "label": "Operating states", "aliases": ["states", "state footprint", "registered states"]},
            {"key": "primary_contact_name", "label": "Primary contact", "aliases": ["contact", "owner"]},
            {"key": "primary_contact_email", "label": "Primary contact email", "aliases": ["email", "contact email"]},
            {"key": "applicable_taxes", "label": "Tax types", "aliases": ["tax scope", "services", "forms"]},
            {"key": "notes", "label": "Notes", "aliases": ["memo", "remarks", "comment"]},
        ]
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or key).strip()
        if not key or not label:
            continue
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        normalized.append({"key": key, "label": label, "aliases": [str(alias) for alias in aliases]})
    return normalized


def _prepare_session(body: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timezone

    session = body.get("session") or {}
    session.setdefault("tenant_id", body["tenant_id"])
    session.setdefault("session_id", body.get("session_id") or "http-session")
    session.setdefault("today", body.get("today") or datetime.now(timezone.utc).date().isoformat())
    session.setdefault("history_window", [])
    session.setdefault("selectable_items", [])
    session.setdefault("current_actions", [])
    session.setdefault("current_workspace", None)
    session.setdefault("previous_workspace", None)
    session.setdefault("breadcrumb", [])
    session.setdefault("operation_log", [])
    session.setdefault("prefetch_pool", {})
    return session


def _instant_response_prefix(user_input: str, session: dict[str, Any]) -> str:
    text = user_input.strip().casefold()
    if not text:
        return "Okay, I will take a look.\n\n"
    if _looks_like_tax_change_need(text):
        return "Okay, I will check which changes may affect your clients.\n\n"
    if any(term in text for term in ["今天", "today", "待处理", "queue"]):
        return "Okay, I will check what needs attention first today.\n\n"
    if _looks_like_comparison_need(text):
        return "Okay, I will compare the relevant items side by side.\n\n"
    if any(term in text for term in ["来源", "变更", "历史", "source", "history", "changed"]):
        return "Okay, I will check the source and change history for this item.\n\n"
    if any(term in text for term in ["起草", "草稿", "邮件", "prepare", "draft", "email"]):
        return "Okay, I will prepare a draft you can review.\n\n"
    return "Okay, I will handle this.\n\n"


def _thinking_status(user_input: str, session: dict[str, Any]) -> str:
    text = user_input.strip().casefold()
    if _looks_like_tax_change_need(text):
        return "Reading the rule library, notices, and recent deadlines."
    if _looks_like_comparison_need(text):
        return "Comparing the current clients, deadlines, and visible work items."
    current_view = session.get("current_view")
    if isinstance(current_view, dict) and current_view.get("type"):
        return "Analyzing the current page with backend data."
    return "Understanding the request and preparing the workspace."


def _looks_like_tax_change_need(text: str) -> bool:
    explicit_terms = [
        "税务新闻",
        "税法新闻",
        "税务变化",
        "税法变化",
        "规则变更",
        "政策变化",
        "政策更新",
        "法规更新",
        "法规变化",
        "税收政策",
        "税务政策",
        "有什么新规",
        "新规",
        "值得关注",
        "tax news",
        "tax change",
        "tax update",
        "policy update",
        "policy change",
        "rule change",
        "regulatory change",
        "notice",
    ]
    if any(term in text for term in explicit_terms):
        return True
    subject_terms = ["政策", "法规", "规则", "税务", "税法", "税收", "policy", "regulation", "rule", "tax"]
    change_terms = ["更新", "变化", "变更", "新闻", "新", "最近", "关注", "update", "change", "news", "recent"]
    return any(term in text for term in subject_terms) and any(term in text for term in change_terms)


def _looks_like_comparison_need(text: str) -> bool:
    comparison_terms = ["哪个", "哪一个", "比较", "对比", "风险", "紧急", "优先", "最紧急", "最重要", "最优先", "compare", "priority", "risk", "urgent"]
    return any(term in text for term in comparison_terms)


def _today_plan(tenant_id: str) -> dict[str, Any]:
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


def _remember_bootstrap_response(session: dict[str, Any], response: dict[str, Any]) -> None:
    remember_response_state(session, response)
    operation = record_operation(
        session,
        user_input="__bootstrap_today__",
        intent_label="today",
        op_class="read",
        plan_source="bootstrap",
        view_type=(response.get("view") or {}).get("type"),
    )
    session["last_turn"] = {
        "user_input": "__bootstrap_today__",
        "intent_label": "today",
        "op_class": "read",
        "plan_source": "bootstrap",
        "template_id": None,
        "similarity": None,
        "view_type": (response.get("view") or {}).get("type"),
        "workspace_ref": operation.get("workspace_ref"),
        "operation_ref": operation.get("operation_id"),
    }


def _latest_new_feedback_event(session: dict[str, Any], previous_count: int) -> dict[str, Any] | None:
    feedback_events = session.get("flywheel_feedback_events", [])
    if len(feedback_events) <= previous_count:
        return None
    return feedback_events[-1]


def _message_chunks(message: str, chunk_size: int = 48) -> list[str]:
    if not message:
        return []
    chunks = []
    start = 0
    natural_breaks = set("。！？；;.!?\n")
    min_chunk = max(12, chunk_size // 2)
    while start < len(message):
        if len(message) - start <= chunk_size:
            chunks.append(message[start:])
            break

        target = min(start + chunk_size, len(message))
        split_at = None
        for index in range(target, start + min_chunk, -1):
            if message[index - 1] in natural_breaks:
                split_at = index
                break
        if split_at is None:
            lookahead_end = min(len(message), target + 24)
            for index in range(target, lookahead_end):
                if message[index] in natural_breaks:
                    split_at = index + 1
                    break
        if split_at is None or split_at <= start:
            split_at = target
        chunks.append(message[start:split_at])
        start = split_at
    return chunks


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
