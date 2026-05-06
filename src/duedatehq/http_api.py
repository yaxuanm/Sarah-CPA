from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from typing import Any

from .app import create_app
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
                    "message": "这个按钮缺少可执行计划，我没有改动任何数据。",
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
            yield _sse("message_delta", {"delta": _instant_response_prefix(user_input, session)})
            yield _sse("thinking", {"message": _thinking_status(user_input, session)})
            previous_feedback_count = len(session.get("flywheel_feedback_events", []))
            try:
                response = app_state.interaction_backend.process_message(user_input, session)
            except Exception as exc:  # noqa: BLE001 - keep SSE stream readable during prototype failures.
                response = {
                    "status": "error",
                    "message": f"这次请求处理失败：{type(exc).__name__}。我没有改动任何数据。",
                    "view": {
                        "type": "GuidanceCard",
                        "data": {
                            "message": "这次请求处理失败，但系统没有写入任何变化。请回到今日列表后再试。",
                            "options": ["查看今天的待处理事项"],
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
            yield _sse("view_rendered", {"view": response.get("view"), "actions": response.get("actions", [])})
            new_feedback = _latest_new_feedback_event(session, previous_feedback_count)
            if new_feedback:
                yield _sse("feedback_recorded", new_feedback)
            for chunk in _message_chunks(str(response.get("message") or "")):
                yield _sse("message_delta", {"delta": chunk})
            yield _sse("done", {"response": response, "session": session})

        return StreamingResponse(events(), media_type="text/event-stream")

    @api.get("/flywheel/stats")
    def flywheel_stats():
        return app_state.intent_library.stats()

    return api


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


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
        return "好的，我来看看。\n\n"
    if _looks_like_tax_change_need(text):
        return "好的，我帮你查一下哪些变化可能影响你的客户。\n\n"
    if any(term in text for term in ["今天", "today", "待处理", "queue"]):
        return "好的，我帮你看看今天哪些事最需要先处理。\n\n"
    if _looks_like_comparison_need(text):
        return "好的，我把相关事项放在一起比较一下。\n\n"
    if any(term in text for term in ["来源", "变更", "历史", "source", "history", "changed"]):
        return "好的，我帮你查这件事的来源和变更记录。\n\n"
    if any(term in text for term in ["起草", "草稿", "邮件", "prepare", "draft", "email"]):
        return "好的，我先帮你准备一版可以检查的内容。\n\n"
    return "好的，我来处理这个问题。\n\n"


def _thinking_status(user_input: str, session: dict[str, Any]) -> str:
    text = user_input.strip().casefold()
    if _looks_like_tax_change_need(text):
        return "正在读取规则库、notice 和近期 deadline。"
    if _looks_like_comparison_need(text):
        return "正在比较当前客户、截止日和可见工作项。"
    current_view = session.get("current_view")
    if isinstance(current_view, dict) and current_view.get("type"):
        return "正在结合当前页面和后台数据分析。"
    return "正在理解需求并准备工作面。"


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
