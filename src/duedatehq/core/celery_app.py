from __future__ import annotations

import os


def get_celery_app(broker_url: str | None = None):
    try:
        from celery import Celery
    except ImportError as exc:
        raise RuntimeError("Celery support requires the optional workers dependencies.") from exc

    resolved_broker = broker_url or os.getenv("DUEDATEHQ_BROKER_URL", "redis://localhost:6379/0")
    app = Celery("duedatehq", broker=resolved_broker, backend=resolved_broker)
    app.conf.task_default_queue = "duedatehq"
    app.conf.task_serializer = "json"
    app.conf.result_serializer = "json"
    app.conf.accept_content = ["json"]
    return app
