from __future__ import annotations

from dataclasses import dataclass

from .celery_app import get_celery_app


@dataclass(slots=True)
class CeleryDispatcher:
    broker_url: str | None = None

    def dispatch_fetch(self, *, source: str | None = None, state: str | None = None, db_url: str | None = None) -> str:
        app = get_celery_app(self.broker_url)
        result = app.send_task("duedatehq.fetch_source", kwargs={"source": source, "state": state, "db_url": db_url})
        return result.id

    def dispatch_schedule_reminders(self, tenant_id: str, db_url: str | None = None) -> str:
        app = get_celery_app(self.broker_url)
        result = app.send_task("duedatehq.schedule_reminders", kwargs={"tenant_id": tenant_id, "db_url": db_url})
        return result.id

    def dispatch_notifications(self, tenant_id: str, db_url: str | None = None) -> str:
        app = get_celery_app(self.broker_url)
        result = app.send_task("duedatehq.send_notifications", kwargs={"tenant_id": tenant_id, "db_url": db_url})
        return result.id
