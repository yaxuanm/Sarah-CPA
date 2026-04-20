from __future__ import annotations

from .app import create_app


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
