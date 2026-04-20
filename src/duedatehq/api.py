from __future__ import annotations

from dataclasses import asdict

from .app import create_app
from .core.conversation import InteractionMode


def get_status(db_path: str | None = None) -> dict[str, object]:
    app = create_app(db_path)
    return {
        "service": "duedatehq",
        "state": "initialized",
        "rules": len(app.engine.list_rules()),
        "review_queue": len(app.engine.list_rule_review_queue()),
        "fetch_runs": len(app.engine.list_fetch_runs()),
        "sources": len(app.engine.list_sources()),
    }


def chat(prompt: str, tenant_id: str | None = None, db_path: str | None = None, mode: str = "text") -> dict[str, object]:
    app = create_app(db_path)
    session = app.conversation.start_session(tenant_id, mode=InteractionMode(mode))
    response = app.conversation.respond(session, prompt, mode=InteractionMode(mode))
    return {
        "session_id": response.session_id,
        "intent": response.intent.value,
        "reply": response.reply,
        "render_blocks": [asdict(item) for item in response.render_blocks],
    }
