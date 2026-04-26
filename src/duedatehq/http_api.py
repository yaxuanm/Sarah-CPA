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
        from fastapi import FastAPI
        from fastapi.responses import StreamingResponse
        from pydantic import BaseModel
    except ImportError as exc:  # pragma: no cover - optional dependency guard.
        raise RuntimeError("FastAPI support requires installing duedatehq[api].") from exc

    app_state = create_app(db_path)
    api = FastAPI(title="DueDateHQ API")

    class ChatBody(BaseModel):
        user_input: str
        tenant_id: str
        session: dict[str, Any] | None = None
        session_id: str | None = None
        today: str | None = None

    @api.post("/chat")
    def chat(body: ChatBody):
        session = _prepare_session(body.model_dump())
        response = app_state.interaction_backend.process_message(body.user_input, session)
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
    def chat_stream(body: ChatBody):
        session = _prepare_session(body.model_dump())

        def events():
            yield _sse("thinking", {"message": "理解请求中。"})
            response = app_state.interaction_backend.process_message(body.user_input, session)
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
            if session.get("flywheel_feedback_events"):
                yield _sse("feedback_recorded", session["flywheel_feedback_events"][-1])
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


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
