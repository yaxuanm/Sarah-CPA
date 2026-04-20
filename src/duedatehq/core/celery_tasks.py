from __future__ import annotations

from ..app import create_app
from .celery_app import get_celery_app
from .fetchers import fetcher_for_source
from .notifiers import ConsoleNotifier, NotifierRegistry
from .models import NotificationChannel
from .workers import FetchWorker, PersistentJobQueue, ReminderScheduler, ReminderWorker


celery_app = get_celery_app()


@celery_app.task(name="duedatehq.fetch_source")
def fetch_source_task(source: str | None = None, state: str | None = None, db_url: str | None = None) -> dict[str, object]:
    app = create_app(db_url)
    worker = FetchWorker(app.engine)
    fetcher = fetcher_for_source(source=source, state=state)
    result = worker.run(source=source, state=state, fetcher=fetcher, actor="celery")
    return {
        "fetch_run_id": result["fetch_run"].fetch_run_id,
        "source": source,
        "state": state,
    }


@celery_app.task(name="duedatehq.schedule_reminders")
def schedule_reminders_task(tenant_id: str, db_url: str | None = None) -> dict[str, object]:
    app = create_app(db_url)
    queue = PersistentJobQueue(app.engine.repositories.storage)
    now = app.engine.clock.now()
    jobs = ReminderScheduler(app.engine, queue).enqueue_next_window(tenant_id, now=now, hours=24)
    dispatched = ReminderWorker(app.engine, queue=queue).run(queue.drain(tenant_id=tenant_id, now=now), now=now)
    return {"tenant_id": tenant_id, "jobs": len(jobs), "dispatched": dispatched}


@celery_app.task(name="duedatehq.send_notifications")
def send_notifications_task(tenant_id: str, db_url: str | None = None) -> dict[str, object]:
    app = create_app(db_url)
    registry = NotifierRegistry(
        {
            NotificationChannel.EMAIL: ConsoleNotifier(NotificationChannel.EMAIL),
            NotificationChannel.SMS: ConsoleNotifier(NotificationChannel.SMS),
            NotificationChannel.SLACK: ConsoleNotifier(NotificationChannel.SLACK),
        }
    )
    sent = app.engine.dispatch_notification_deliveries(tenant_id, registry, actor="celery")
    return {"tenant_id": tenant_id, "sent": sent}
