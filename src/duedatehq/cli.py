from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from .app import build_storage, create_app
from .core.dispatchers import CeleryDispatcher
from .core.postgres import PostgresStorage
from .core.fetchers import FileFetcher, HtmlFetcher, HttpTextFetcher, PdfFetcher, RssEntryFetcher, fetcher_for_source
from .core.models import DeadlineAction, NotificationChannel
from .core.notifiers import ConsoleNotifier, JsonWebhookNotifier, NotifierRegistry, SMTPEmailNotifier
from .core.workers import FetchWorker, PersistentJobQueue, ReminderScheduler, ReminderWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="duedatehq")
    parser.add_argument("--db", dest="db_path", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    tenant_parser = subparsers.add_parser("tenant")
    tenant_subparsers = tenant_parser.add_subparsers(dest="tenant_command", required=True)
    tenant_add = tenant_subparsers.add_parser("add")
    tenant_add.add_argument("name")

    client_parser = subparsers.add_parser("client")
    client_subparsers = client_parser.add_subparsers(dest="client_command", required=True)
    client_add = client_subparsers.add_parser("add")
    client_add.add_argument("tenant_id")
    client_add.add_argument("name")
    client_add.add_argument("--entity", required=True)
    client_add.add_argument("--states", required=True)
    client_add.add_argument("--tax-year", type=int, required=True)
    client_update = client_subparsers.add_parser("update-states")
    client_update.add_argument("tenant_id")
    client_update.add_argument("client_id")
    client_update.add_argument("--states", required=True)
    client_list = client_subparsers.add_parser("list")
    client_list.add_argument("tenant_id")

    rule_parser = subparsers.add_parser("rule")
    rule_subparsers = rule_parser.add_subparsers(dest="rule_command", required=True)
    rule_ingest = rule_subparsers.add_parser("ingest-text")
    rule_ingest.add_argument("--source-url", required=True)
    rule_ingest.add_argument("--text-file", required=True)
    rule_ingest.add_argument("--fetched-at", default=None)
    rule_add = rule_subparsers.add_parser("add")
    rule_add.add_argument("--tax-type", required=True)
    rule_add.add_argument("--jurisdiction", required=True)
    rule_add.add_argument("--entity-types", required=True)
    rule_add.add_argument("--deadline-date", required=True)
    rule_add.add_argument("--effective-from", required=True)
    rule_add.add_argument("--source-url", required=True)
    rule_add.add_argument("--confidence", type=float, default=0.99)
    rule_list = rule_subparsers.add_parser("list")
    rule_review = rule_subparsers.add_parser("review-queue")

    fetch_parser = subparsers.add_parser("fetch")
    fetch_group = fetch_parser.add_mutually_exclusive_group(required=True)
    fetch_group.add_argument("--source")
    fetch_group.add_argument("--state")
    fetch_group.add_argument("--all", action="store_true")
    fetch_parser.add_argument("--text-file")
    fetch_parser.add_argument("--source-url")
    fetch_parser.add_argument("--fetched-at", default=None)
    fetch_parser.add_argument("--list-sources", action="store_true")

    deadline_parser = subparsers.add_parser("deadline")
    deadline_subparsers = deadline_parser.add_subparsers(dest="deadline_command", required=True)
    deadline_list = deadline_subparsers.add_parser("list")
    deadline_list.add_argument("tenant_id")
    deadline_list.add_argument("--client", dest="client_id")
    deadline_list.add_argument("--show-reminders", action="store_true")
    deadline_action = deadline_subparsers.add_parser("action")
    deadline_action.add_argument("tenant_id")
    deadline_action.add_argument("deadline_id")
    deadline_action.add_argument("action", choices=[item.value for item in DeadlineAction if item is not DeadlineAction.RESUME])
    deadline_action.add_argument("--until")
    deadline_action.add_argument("--new-date")
    deadline_action.add_argument("--actor", default="cli")
    deadline_trigger = deadline_subparsers.add_parser("trigger-reminders")
    deadline_trigger.add_argument("--at", default=None)
    deadline_trigger.add_argument("--tenant-id", required=True)
    deadline_transitions = deadline_subparsers.add_parser("transitions")
    deadline_transitions.add_argument("tenant_id")
    deadline_transitions.add_argument("deadline_id")

    log_parser = subparsers.add_parser("log")
    log_parser.add_argument("--tenant-id")
    log_parser.add_argument("--object-id")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("tenant_id")
    export_parser.add_argument("--actor", default="cli")

    today_parser = subparsers.add_parser("today")
    today_parser.add_argument("tenant_id")
    today_parser.add_argument("--limit", type=int, default=5)

    notify_parser = subparsers.add_parser("notify")
    notify_subparsers = notify_parser.add_subparsers(dest="notify_command", required=True)
    notify_config = notify_subparsers.add_parser("config")
    notify_config_subparsers = notify_config.add_subparsers(dest="notify_config_command", required=True)
    notify_config_add = notify_config_subparsers.add_parser("add")
    notify_config_add.add_argument("tenant_id")
    notify_config_add.add_argument("--channel", choices=[item.value for item in NotificationChannel], required=True)
    notify_config_add.add_argument("--destination", required=True)
    notify_config_list = notify_config_subparsers.add_parser("list")
    notify_config_list.add_argument("tenant_id")
    notify_preview = notify_subparsers.add_parser("preview")
    notify_preview.add_argument("tenant_id")
    notify_preview.add_argument("--within-days", type=int, default=7)
    notify_history = notify_subparsers.add_parser("history")
    notify_history.add_argument("tenant_id")
    notify_send = notify_subparsers.add_parser("send-pending")
    notify_send.add_argument("tenant_id")
    notify_send.add_argument("--smtp-host")
    notify_send.add_argument("--smtp-port", type=int, default=25)
    notify_send.add_argument("--smtp-sender")
    notify_send.add_argument("--sms-webhook")
    notify_send.add_argument("--slack-webhook")

    worker_parser = subparsers.add_parser("worker")
    worker_subparsers = worker_parser.add_subparsers(dest="worker_command", required=True)
    worker_fetch = worker_subparsers.add_parser("fetch")
    worker_fetch.add_argument("--source")
    worker_fetch.add_argument("--state")
    worker_fetch_mode = worker_fetch.add_mutually_exclusive_group(required=False)
    worker_fetch_mode.add_argument("--text-file")
    worker_fetch_mode.add_argument("--url")
    worker_fetch_mode.add_argument("--rss-url")
    worker_fetch.add_argument("--format", choices=["text", "html", "pdf"], default="html")
    worker_fetch.add_argument("--source-url")
    worker_fetch.add_argument("--fetched-at", default=None)
    worker_fetch.add_argument("--entry-title-contains")
    worker_scheduler = worker_subparsers.add_parser("schedule-reminders")
    worker_scheduler.add_argument("tenant_id")
    worker_scheduler.add_argument("--at", default=None)
    worker_scheduler.add_argument("--hours", type=int, default=24)
    worker_jobs = worker_subparsers.add_parser("jobs")
    worker_jobs.add_argument("--tenant-id")
    celery_parser = subparsers.add_parser("celery")
    celery_subparsers = celery_parser.add_subparsers(dest="celery_command", required=True)
    celery_ping = celery_subparsers.add_parser("ping")
    celery_ping.add_argument("--broker-url", required=False)
    celery_fetch = celery_subparsers.add_parser("dispatch-fetch")
    celery_fetch.add_argument("--broker-url", required=False)
    celery_fetch.add_argument("--source")
    celery_fetch.add_argument("--state")
    celery_schedule = celery_subparsers.add_parser("dispatch-reminders")
    celery_schedule.add_argument("tenant_id")
    celery_schedule.add_argument("--broker-url", required=False)
    celery_notify = celery_subparsers.add_parser("dispatch-notifications")
    celery_notify.add_argument("tenant_id")
    celery_notify.add_argument("--broker-url", required=False)

    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_subparsers.add_parser("init")
    db_subparsers.add_parser("status")
    db_subparsers.add_parser("rls-check")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "db":
        storage = build_storage(args.db_path)
        if args.db_command == "init":
            if isinstance(storage, PostgresStorage):
                storage.initialize()
                print_json({"database": "postgresql", "status": "initialized"})
                return 0
            print_json({"database": "sqlite", "status": "initialized"})
            return 0
        if args.db_command == "status":
            if isinstance(storage, PostgresStorage):
                print_json(storage.healthcheck())
                return 0
            print_json({"database": "sqlite", "path": str(storage.db_path)})
            return 0
        if args.db_command == "rls-check":
            if not isinstance(storage, PostgresStorage):
                parser.error("db rls-check requires a PostgreSQL DSN")
            print_json(storage.run_rls_self_test())
            return 0

    app = create_app(args.db_path)
    engine = app.engine

    if args.command == "tenant" and args.tenant_command == "add":
        print_json({"tenant_id": engine.create_tenant(args.name).tenant_id})
        return 0

    if args.command == "client":
        if args.client_command == "add":
            client = engine.register_client(
                tenant_id=args.tenant_id,
                name=args.name,
                entity_type=args.entity,
                registered_states=split_csv(args.states),
                tax_year=args.tax_year,
                actor="cli",
            )
            print_json({"client_id": client.client_id, "tenant_id": client.tenant_id})
            return 0
        if args.client_command == "update-states":
            client = engine.update_client_states(
                tenant_id=args.tenant_id,
                client_id=args.client_id,
                registered_states=split_csv(args.states),
                actor="cli",
            )
            print_json({"client_id": client.client_id, "registered_states": client.registered_states})
            return 0
        if args.client_command == "list":
            print_json([serialize(client) for client in engine.list_clients(args.tenant_id)], default=str)
            return 0

    if args.command == "rule":
        if args.rule_command == "ingest-text":
            raw_text = Path(args.text_file).read_text(encoding="utf-8")
            fetched_at = parse_ts(args.fetched_at) if args.fetched_at else datetime.now(timezone.utc)
            result = engine.ingest_rule_text(raw_text, args.source_url, fetched_at, actor="cli")
            print_json(serialize(result), default=str)
            return 0
        if args.rule_command == "add":
            rule = engine.create_rule(
                tax_type=args.tax_type,
                jurisdiction=args.jurisdiction,
                entity_types=split_csv(args.entity_types),
                deadline_date=args.deadline_date,
                effective_from=args.effective_from,
                source_url=args.source_url,
                confidence_score=args.confidence,
                actor="cli",
            )
            print_json(serialize(rule), default=str)
            return 0
        if args.rule_command == "list":
            print_json([serialize(rule) for rule in engine.list_rules()], default=str)
            return 0
        if args.rule_command == "review-queue":
            print_json([serialize(item) for item in engine.list_rule_review_queue()], default=str)
            return 0

    if args.command == "fetch":
        if args.list_sources:
            print_json(engine.list_sources(), default=str)
            return 0
        if args.all:
            print_json(engine.list_sources(), default=str)
            return 0
        if not args.text_file or not args.source_url:
            parser.error("fetch requires --text-file and --source-url unless --list-sources or --all is used")
        raw_text = Path(args.text_file).read_text(encoding="utf-8")
        fetched_at = parse_ts(args.fetched_at) if args.fetched_at else datetime.now(timezone.utc)
        result = engine.fetch_from_source(
            source=args.source,
            state=args.state,
            raw_text=raw_text,
            source_url=args.source_url,
            fetched_at=fetched_at,
            actor="cli",
        )
        print_json({"fetch_run": serialize(result["fetch_run"]), "result": serialize(result["result"])}, default=str)
        return 0

    if args.command == "deadline":
        if args.deadline_command == "list":
            deadlines = engine.list_deadlines(args.tenant_id, args.client_id)
            payload = []
            for deadline in deadlines:
                item = serialize(deadline)
                if args.show_reminders:
                    item["reminders"] = [serialize(reminder) for reminder in engine.list_reminders(args.tenant_id, deadline.deadline_id)]
                payload.append(item)
            print_json(payload, default=str)
            return 0
        if args.deadline_command == "action":
            metadata: dict[str, str] = {}
            if args.until:
                metadata["until"] = args.until
            if args.new_date:
                metadata["new_date"] = args.new_date
            result = engine.apply_deadline_action(
                tenant_id=args.tenant_id,
                deadline_id=args.deadline_id,
                action=DeadlineAction(args.action),
                actor=args.actor,
                metadata=metadata,
            )
            print_json(result)
            return 0
        if args.deadline_command == "trigger-reminders":
            triggered = engine.trigger_due_reminders(parse_ts(args.at) if args.at else None, tenant_id=args.tenant_id)
            reminders = engine.list_reminders(args.tenant_id)
            print_json({"triggered": triggered, "reminders": [serialize(item) for item in reminders]}, default=str)
            return 0
        if args.deadline_command == "transitions":
            print_json([serialize(item) for item in engine.list_transitions(args.deadline_id, args.tenant_id)], default=str)
            return 0

    if args.command == "log":
        print_json([serialize(item) for item in engine.list_audit_logs(args.tenant_id, args.object_id)], default=str)
        return 0

    if args.command == "export":
        print_json(engine.export_deadlines(args.tenant_id, args.actor), default=str)
        return 0

    if args.command == "today":
        print_json([serialize(item) for item in engine.today(args.tenant_id, args.limit)], default=str)
        return 0

    if args.command == "notify":
        if args.notify_command == "config":
            if args.notify_config_command == "add":
                route = engine.configure_notification_route(
                    tenant_id=args.tenant_id,
                    channel=NotificationChannel(args.channel),
                    destination=args.destination,
                    actor="cli",
                )
                print_json(serialize(route), default=str)
                return 0
            if args.notify_config_command == "list":
                print_json([serialize(item) for item in engine.list_notification_routes(args.tenant_id)], default=str)
                return 0
        if args.notify_command == "preview":
            print_json([serialize(item) for item in engine.notify_preview(args.tenant_id, args.within_days)], default=str)
            return 0
        if args.notify_command == "history":
            print_json([serialize(item) for item in engine.notify_history(args.tenant_id)], default=str)
            return 0
        if args.notify_command == "send-pending":
            registry = build_notifier_registry(args)
            sent = engine.dispatch_notification_deliveries(args.tenant_id, registry, actor="cli")
            print_json(
                {
                    "sent": sent,
                    "deliveries": [serialize(item) for item in engine.list_notification_deliveries(args.tenant_id)],
                },
                default=str,
            )
            return 0

    if args.command == "worker":
        if args.worker_command == "fetch":
            worker = FetchWorker(engine)
            fetched_at = parse_ts(args.fetched_at) if args.fetched_at else None
            if args.text_file:
                if not args.source_url:
                    parser.error("worker fetch with --text-file requires --source-url")
                fetcher = FileFetcher(
                    path=Path(args.text_file),
                    source_url=args.source_url,
                    fetched_at=fetched_at,
                )
            elif args.url:
                if args.format == "text":
                    fetcher = HttpTextFetcher(url=args.url, fetched_at=fetched_at)
                elif args.format == "pdf":
                    fetcher = PdfFetcher(url=args.url, fetched_at=fetched_at)
                else:
                    fetcher = HtmlFetcher(url=args.url, fetched_at=fetched_at)
            elif args.rss_url:
                fetcher = RssEntryFetcher(
                    url=args.rss_url,
                    entry_title_contains=args.entry_title_contains,
                    fetched_at=fetched_at,
                )
            else:
                fetcher = fetcher_for_source(source=args.source, state=args.state, fetched_at=fetched_at)
            result = worker.run(source=args.source, state=args.state, fetcher=fetcher)
            print_json({"fetch_run": serialize(result["fetch_run"]), "result": serialize(result["result"])}, default=str)
            return 0
        if args.worker_command == "schedule-reminders":
            now = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
            queue = PersistentJobQueue(app.engine.repositories.storage)
            scheduler = ReminderScheduler(engine, queue)
            jobs = scheduler.enqueue_next_window(args.tenant_id, now=now, hours=args.hours)
            dispatched = ReminderWorker(engine, queue=queue).run(queue.drain(tenant_id=args.tenant_id, now=now), now=now)
            print_json({"jobs": [serialize(job) for job in jobs], "dispatched": dispatched}, default=str)
            return 0
        if args.worker_command == "jobs":
            queue = PersistentJobQueue(app.engine.repositories.storage)
            print_json([serialize(job) for job in queue.list_jobs(args.tenant_id)], default=str)
            return 0

    if args.command == "celery":
        from .core.celery_app import get_celery_app

        app_instance = get_celery_app(getattr(args, "broker_url", None))
        if args.celery_command == "ping":
            print_json({"broker_url": app_instance.conf.broker_url, "task_default_queue": app_instance.conf.task_default_queue})
            return 0
        dispatcher = CeleryDispatcher(getattr(args, "broker_url", None))
        if args.celery_command == "dispatch-fetch":
            task_id = dispatcher.dispatch_fetch(source=args.source, state=args.state, db_url=args.db_path)
            print_json({"task_id": task_id, "task": "duedatehq.fetch_source"})
            return 0
        if args.celery_command == "dispatch-reminders":
            task_id = dispatcher.dispatch_schedule_reminders(args.tenant_id, db_url=args.db_path)
            print_json({"task_id": task_id, "task": "duedatehq.schedule_reminders"})
            return 0
        if args.celery_command == "dispatch-notifications":
            task_id = dispatcher.dispatch_notifications(args.tenant_id, db_url=args.db_path)
            print_json({"task_id": task_id, "task": "duedatehq.send_notifications"})
            return 0

    return 1


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def print_json(payload, default=None) -> None:
    print(json.dumps(payload, indent=2, default=default, sort_keys=True))


def serialize(value):
    if is_dataclass(value):
        return asdict(value)
    return value


def build_notifier_registry(args) -> NotifierRegistry:
    notifiers = {
        NotificationChannel.EMAIL: ConsoleNotifier(NotificationChannel.EMAIL),
        NotificationChannel.SMS: ConsoleNotifier(NotificationChannel.SMS),
        NotificationChannel.SLACK: ConsoleNotifier(NotificationChannel.SLACK),
    }
    if args.smtp_host and args.smtp_sender:
        notifiers[NotificationChannel.EMAIL] = SMTPEmailNotifier(args.smtp_host, args.smtp_port, args.smtp_sender)
    if args.sms_webhook:
        notifiers[NotificationChannel.SMS] = JsonWebhookNotifier(NotificationChannel.SMS, args.sms_webhook)
    if args.slack_webhook:
        notifiers[NotificationChannel.SLACK] = JsonWebhookNotifier(NotificationChannel.SLACK, args.slack_webhook)
    return NotifierRegistry(notifiers)


if __name__ == "__main__":
    raise SystemExit(main())
