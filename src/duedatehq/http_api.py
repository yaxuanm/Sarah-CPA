from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .app import create_app


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

    @api.post("/action")
    def action(plan: dict[str, Any], tenant_id: str, session_id: str | None = None):
        session = {"tenant_id": tenant_id, "session_id": session_id or "http-action"}
        response = app_state.interaction_backend.process_action(plan, session)
        return {"response": response, "session": session}

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
            yield _sse("thinking", {"message": "理解请求中。"})
            previous_feedback_count = len(session.get("flywheel_feedback_events", []))
            try:
                response = app_state.interaction_backend.process_message(body["user_input"], session)
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


def _prepare_session(body: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timezone

    session = body.get("session") or {}
    session.setdefault("tenant_id", body["tenant_id"])
    session.setdefault("session_id", body.get("session_id") or "http-session")
    session.setdefault("today", body.get("today") or datetime.now(timezone.utc).date().isoformat())
    return session


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
