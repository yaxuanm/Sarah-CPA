from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from .app import build_storage, create_app
from .core.conversation import InteractionMode
from .core.dispatchers import CeleryDispatcher
from .core.postgres import PostgresStorage
from .core.fetchers import FileFetcher, HtmlFetcher, HttpTextFetcher, PdfFetcher, RssEntryFetcher, fetcher_for_source
from .core.models import BlockerStatus, DeadlineAction, DeadlineStatus, NotificationChannel, TaskStatus
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
    client_add.add_argument("--client-type", default="business")
    client_add.add_argument("--legal-name")
    client_add.add_argument("--home-jurisdiction")
    client_add.add_argument("--contact-name")
    client_add.add_argument("--contact-email")
    client_add.add_argument("--contact-phone")
    client_add.add_argument("--preferred-channel")
    client_add.add_argument("--responsible-cpa")
    client_add.add_argument("--entity-election")
    client_add.add_argument("--intake-status", default="draft")
    client_add.add_argument("--profile-source", default="manual")
    client_add.add_argument("--first-year-filing", action=argparse.BooleanOptionalAction, default=None)
    client_add.add_argument("--final-year-filing", action=argparse.BooleanOptionalAction, default=None)
    client_add.add_argument("--extension-requested", action=argparse.BooleanOptionalAction, default=None)
    client_add.add_argument("--extension-filed", action=argparse.BooleanOptionalAction, default=None)
    client_add.add_argument("--estimated-tax-required", action=argparse.BooleanOptionalAction, default=None)
    client_add.add_argument("--payroll-present", action=argparse.BooleanOptionalAction, default=None)
    client_add.add_argument("--contractor-reporting-required", action=argparse.BooleanOptionalAction, default=None)
    client_add.add_argument("--notice-received", action=argparse.BooleanOptionalAction, default=None)
    client_update = client_subparsers.add_parser("update-states")
    client_update.add_argument("tenant_id")
    client_update.add_argument("client_id")
    client_update.add_argument("--states", required=True)
    client_show = client_subparsers.add_parser("show")
    client_show.add_argument("tenant_id")
    client_show.add_argument("client_id")
    client_profile = client_subparsers.add_parser("update-profile")
    client_profile.add_argument("tenant_id")
    client_profile.add_argument("client_id")
    client_profile.add_argument("--tax-year", type=int, required=True)
    client_profile.add_argument("--entity-election")
    client_profile.add_argument("--intake-status")
    client_profile.add_argument("--profile-source")
    client_profile.add_argument("--first-year-filing", action=argparse.BooleanOptionalAction, default=None)
    client_profile.add_argument("--final-year-filing", action=argparse.BooleanOptionalAction, default=None)
    client_profile.add_argument("--extension-requested", action=argparse.BooleanOptionalAction, default=None)
    client_profile.add_argument("--extension-filed", action=argparse.BooleanOptionalAction, default=None)
    client_profile.add_argument("--estimated-tax-required", action=argparse.BooleanOptionalAction, default=None)
    client_profile.add_argument("--payroll-present", action=argparse.BooleanOptionalAction, default=None)
    client_profile.add_argument("--contractor-reporting-required", action=argparse.BooleanOptionalAction, default=None)
    client_profile.add_argument("--notice-received", action=argparse.BooleanOptionalAction, default=None)
    client_list = client_subparsers.add_parser("list")
    client_list.add_argument("tenant_id")

    task_parser = subparsers.add_parser("task")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)
    task_add = task_subparsers.add_parser("add")
    task_add.add_argument("tenant_id")
    task_add.add_argument("client_id")
    task_add.add_argument("--title", required=True)
    task_add.add_argument("--description")
    task_add.add_argument("--task-type", default="manual")
    task_add.add_argument("--priority", default="normal")
    task_add.add_argument("--source-type", default="manual")
    task_add.add_argument("--source-id")
    task_add.add_argument("--owner-user-id")
    task_add.add_argument("--due-at")
    task_add.add_argument("--actor", default="cli")
    task_list = task_subparsers.add_parser("list")
    task_list.add_argument("tenant_id")
    task_list.add_argument("--client", dest="client_id")
    task_list.add_argument("--status", choices=[item.value for item in TaskStatus])
    task_list.add_argument("--source-type")
    task_list.add_argument("--limit", type=int)
    task_update = task_subparsers.add_parser("update-status")
    task_update.add_argument("tenant_id")
    task_update.add_argument("task_id")
    task_update.add_argument("--status", choices=[item.value for item in TaskStatus], required=True)
    task_update.add_argument("--actor", default="cli")

    blocker_parser = subparsers.add_parser("blocker")
    blocker_subparsers = blocker_parser.add_subparsers(dest="blocker_command", required=True)
    blocker_add = blocker_subparsers.add_parser("add")
    blocker_add.add_argument("tenant_id")
    blocker_add.add_argument("client_id")
    blocker_add.add_argument("--title", required=True)
    blocker_add.add_argument("--description")
    blocker_add.add_argument("--blocker-type", default="missing_info")
    blocker_add.add_argument("--source-type", default="manual")
    blocker_add.add_argument("--source-id")
    blocker_add.add_argument("--owner-user-id")
    blocker_add.add_argument("--actor", default="cli")
    blocker_list = blocker_subparsers.add_parser("list")
    blocker_list.add_argument("tenant_id")
    blocker_list.add_argument("--client", dest="client_id")
    blocker_list.add_argument("--status", choices=[item.value for item in BlockerStatus])
    blocker_list.add_argument("--source-type")
    blocker_list.add_argument("--limit", type=int)
    blocker_update = blocker_subparsers.add_parser("update-status")
    blocker_update.add_argument("tenant_id")
    blocker_update.add_argument("blocker_id")
    blocker_update.add_argument("--status", choices=[item.value for item in BlockerStatus], required=True)
    blocker_update.add_argument("--actor", default="cli")

    notice_parser = subparsers.add_parser("notice")
    notice_subparsers = notice_parser.add_subparsers(dest="notice_command", required=True)
    notice_generate = notice_subparsers.add_parser("generate-work")
    notice_generate.add_argument("tenant_id")
    notice_generate.add_argument("--notice-id", required=True)
    notice_generate.add_argument("--title", required=True)
    notice_generate.add_argument("--source-url", required=True)
    notice_generate.add_argument("--impacts-file", required=True)
    notice_generate.add_argument("--actor", default="cli")

    import_parser = subparsers.add_parser("import")
    import_subparsers = import_parser.add_subparsers(dest="import_command", required=True)
    import_preview = import_subparsers.add_parser("preview")
    import_preview.add_argument("--csv", required=True)
    import_apply = import_subparsers.add_parser("apply")
    import_apply.add_argument("tenant_id")
    import_apply.add_argument("--csv", required=True)
    import_apply.add_argument("--tax-year", type=int, required=True)
    import_apply.add_argument("--default-client-type", default="business")
    import_apply.add_argument("--actor", default="cli")

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

    source_parser = subparsers.add_parser("source")
    source_subparsers = source_parser.add_subparsers(dest="source_command", required=True)
    source_list = source_subparsers.add_parser("list")
    source_list.add_argument("--supported-sync", action="store_true")
    source_sync = source_subparsers.add_parser("sync")
    source_sync.add_argument("--source", action="append")
    source_sync.add_argument("--state", action="append")
    source_sync.add_argument("--all", action="store_true")
    source_sync.add_argument("--fetched-at", default=None)

    deadline_parser = subparsers.add_parser("deadline")
    deadline_subparsers = deadline_parser.add_subparsers(dest="deadline_command", required=True)
    deadline_list = deadline_subparsers.add_parser("list")
    deadline_list.add_argument("tenant_id")
    deadline_list.add_argument("--client", dest="client_id")
    deadline_list.add_argument("--within-days", type=int)
    deadline_list.add_argument("--status", choices=[item.value for item in DeadlineStatus])
    deadline_list.add_argument("--jurisdiction")
    deadline_list.add_argument("--limit", type=int)
    deadline_list.add_argument("--offset", type=int, default=0)
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
    deadline_available_actions = deadline_subparsers.add_parser("available-actions")
    deadline_available_actions.add_argument("tenant_id")
    deadline_available_actions.add_argument("deadline_id")

    log_parser = subparsers.add_parser("log")
    log_parser.add_argument("--tenant-id")
    log_parser.add_argument("--object-id")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("tenant_id")
    export_parser.add_argument("--client", dest="client_id")
    export_parser.add_argument("--format", choices=["json", "csv"], default="json")
    export_parser.add_argument("--actor", default="cli")

    today_parser = subparsers.add_parser("today")
    today_parser.add_argument("tenant_id")
    today_parser.add_argument("--limit", type=int, default=5)
    today_parser.add_argument("--enrich", action="store_true")

    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("--tenant-id")
    chat_parser.add_argument("--mode", choices=[item.value for item in InteractionMode], default=InteractionMode.TEXT.value)
    chat_parser.add_argument("--prompt")
    chat_parser.add_argument("--transcript-file")

    flywheel_parser = subparsers.add_parser("flywheel")
    flywheel_subparsers = flywheel_parser.add_subparsers(dest="flywheel_command", required=True)
    flywheel_subparsers.add_parser("stats")
    flywheel_templates = flywheel_subparsers.add_parser("templates")
    flywheel_templates.add_argument("--status")
    flywheel_templates.add_argument("--limit", type=int, default=50)
    flywheel_feedback = flywheel_subparsers.add_parser("feedback")
    flywheel_feedback.add_argument("--signal")
    flywheel_feedback.add_argument("--limit", type=int, default=50)
    flywheel_review = flywheel_subparsers.add_parser("review-queue")
    flywheel_review.add_argument("--limit", type=int, default=50)

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
                client_type=args.client_type,
                legal_name=args.legal_name,
                home_jurisdiction=args.home_jurisdiction,
                primary_contact_name=args.contact_name,
                primary_contact_email=args.contact_email,
                primary_contact_phone=args.contact_phone,
                preferred_communication_channel=args.preferred_channel,
                responsible_cpa=args.responsible_cpa,
                entity_election=args.entity_election,
                first_year_filing=args.first_year_filing,
                final_year_filing=args.final_year_filing,
                extension_requested=args.extension_requested,
                extension_filed=args.extension_filed,
                estimated_tax_required=args.estimated_tax_required,
                payroll_present=args.payroll_present,
                contractor_reporting_required=args.contractor_reporting_required,
                notice_received=args.notice_received,
                intake_status=args.intake_status,
                profile_source=args.profile_source,
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
        if args.client_command == "show":
            bundle = engine.get_client_bundle(args.tenant_id, args.client_id)
            print_json(
                {
                    "client": serialize(bundle["client"]),
                    "tax_profiles": [serialize(item) for item in bundle["tax_profiles"]],
                    "jurisdictions": [serialize(item) for item in bundle["jurisdictions"]],
                    "contacts": [serialize(item) for item in bundle["contacts"]],
                    "tasks": [serialize(item) for item in bundle["tasks"]],
                    "blockers": [serialize(item) for item in bundle["blockers"]],
                    "deadlines": [serialize(item) for item in bundle["deadlines"]],
                },
                default=str,
            )
            return 0
        if args.client_command == "update-profile":
            profile = engine.update_client_tax_profile(
                tenant_id=args.tenant_id,
                client_id=args.client_id,
                tax_year=args.tax_year,
                entity_election=args.entity_election,
                first_year_filing=args.first_year_filing,
                final_year_filing=args.final_year_filing,
                extension_requested=args.extension_requested,
                extension_filed=args.extension_filed,
                estimated_tax_required=args.estimated_tax_required,
                payroll_present=args.payroll_present,
                contractor_reporting_required=args.contractor_reporting_required,
                notice_received=args.notice_received,
                intake_status=args.intake_status,
                profile_source=args.profile_source,
                actor="cli",
            )
            print_json(serialize(profile), default=str)
            return 0
        if args.client_command == "list":
            print_json([serialize(client) for client in engine.list_clients(args.tenant_id)], default=str)
            return 0

    if args.command == "task":
        if args.task_command == "add":
            task = engine.create_task(
                tenant_id=args.tenant_id,
                client_id=args.client_id,
                title=args.title,
                description=args.description,
                task_type=args.task_type,
                priority=args.priority,
                source_type=args.source_type,
                source_id=args.source_id,
                owner_user_id=args.owner_user_id,
                due_at=parse_ts(args.due_at) if args.due_at else None,
                actor=args.actor,
            )
            print_json(serialize(task), default=str)
            return 0
        if args.task_command == "list":
            tasks = engine.list_tasks(
                args.tenant_id,
                args.client_id,
                status=TaskStatus(args.status) if args.status else None,
                source_type=args.source_type,
                limit=args.limit,
            )
            print_json([serialize(task) for task in tasks], default=str)
            return 0
        if args.task_command == "update-status":
            task = engine.update_task_status(
                tenant_id=args.tenant_id,
                task_id=args.task_id,
                status=TaskStatus(args.status),
                actor=args.actor,
            )
            print_json(serialize(task), default=str)
            return 0

    if args.command == "import":
        if args.import_command == "preview":
            preview = engine.preview_import_csv(args.csv)
            print_json(preview, default=str)
            return 0
        if args.import_command == "apply":
            result = engine.apply_import_csv(
                tenant_id=args.tenant_id,
                csv_path=args.csv,
                tax_year=args.tax_year,
                default_client_type=args.default_client_type,
                actor=args.actor,
            )
            print_json(
                {
                    "source_name": result["source_name"],
                    "created_clients": [serialize(client) for client in result["created_clients"]],
                    "created_blockers": [serialize(blocker) for blocker in result["created_blockers"]],
                    "created_tasks": [serialize(task) for task in result["created_tasks"]],
                    "skipped_rows": result["skipped_rows"],
                    "dashboard": {
                        "today": result["dashboard"]["today"],
                        "active_work": [serialize(task) for task in result["dashboard"]["active_work"]],
                        "waiting_on_info": [serialize(blocker) for blocker in result["dashboard"]["waiting_on_info"]],
                        "client_count": result["dashboard"]["client_count"],
                        "open_task_count": result["dashboard"]["open_task_count"],
                        "open_blocker_count": result["dashboard"]["open_blocker_count"],
                    },
                },
                default=str,
            )
            return 0

    if args.command == "blocker":
        if args.blocker_command == "add":
            blocker = engine.create_blocker(
                tenant_id=args.tenant_id,
                client_id=args.client_id,
                title=args.title,
                description=args.description,
                blocker_type=args.blocker_type,
                source_type=args.source_type,
                source_id=args.source_id,
                owner_user_id=args.owner_user_id,
                actor=args.actor,
            )
            print_json(serialize(blocker), default=str)
            return 0
        if args.blocker_command == "list":
            blockers = engine.list_blockers(
                args.tenant_id,
                args.client_id,
                status=BlockerStatus(args.status) if args.status else None,
                source_type=args.source_type,
                limit=args.limit,
            )
            print_json([serialize(blocker) for blocker in blockers], default=str)
            return 0
        if args.blocker_command == "update-status":
            blocker = engine.update_blocker_status(
                tenant_id=args.tenant_id,
                blocker_id=args.blocker_id,
                status=BlockerStatus(args.status),
                actor=args.actor,
            )
            print_json(serialize(blocker), default=str)
            return 0

    if args.command == "notice":
        if args.notice_command == "generate-work":
            impacts = json.loads(Path(args.impacts_file).read_text(encoding="utf-8"))
            result = engine.generate_notice_work(
                tenant_id=args.tenant_id,
                notice_id=args.notice_id,
                title=args.title,
                source_url=args.source_url,
                affected_clients=impacts,
                actor=args.actor,
            )
            print_json(
                {
                    "notice_id": result["notice_id"],
                    "title": result["title"],
                    "source_url": result["source_url"],
                    "tasks": [serialize(task) for task in result["tasks"]],
                    "blockers": [serialize(blocker) for blocker in result["blockers"]],
                    "skipped_clients": result["skipped_clients"],
                },
                default=str,
            )
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

    if args.command == "source":
        if args.source_command == "list":
            sources = engine.list_sources()
            if args.supported_sync:
                sources = {key: value for key, value in sources.items() if key in {"state_ca", "state_tx", "state_ny"}}
            print_json(sources, default=str)
            return 0
        if args.source_command == "sync":
            fetched_at = parse_ts(args.fetched_at) if args.fetched_at else None
            results = engine.sync_official_sources(
                sources=args.source,
                states=args.state,
                all_supported=args.all,
                fetched_at=fetched_at,
                actor="cli",
            )
            print_json(
                [
                    {"fetch_run": serialize(result["fetch_run"]), "result": serialize(result["result"])}
                    for result in results
                ],
                default=str,
            )
            return 0

    if args.command == "deadline":
        if args.deadline_command == "list":
            deadlines = engine.list_deadlines(
                args.tenant_id,
                args.client_id,
                within_days=args.within_days,
                status=DeadlineStatus(args.status) if args.status else None,
                jurisdiction=args.jurisdiction,
                limit=args.limit,
                offset=args.offset,
            )
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
        if args.deadline_command == "available-actions":
            print_json(engine.available_deadline_actions(args.tenant_id, args.deadline_id), default=str)
            return 0

    if args.command == "log":
        print_json([serialize(item) for item in engine.list_audit_logs(args.tenant_id, args.object_id)], default=str)
        return 0

    if args.command == "export":
        exported = engine.export_deadlines(args.tenant_id, args.actor, client_id=args.client_id)
        if args.format == "csv":
            print(print_csv_rows(exported), end="")
            return 0
        print_json(exported, default=str)
        return 0

    if args.command == "today":
        if args.enrich:
            print_json(engine.today_enriched(args.tenant_id, args.limit), default=str)
            return 0
        print_json([serialize(item) for item in engine.today(args.tenant_id, args.limit)], default=str)
        return 0

    if args.command == "chat":
        mode = InteractionMode(args.mode)
        conversation = app.conversation
        session = conversation.start_session(args.tenant_id, mode=mode)
        if args.prompt or args.transcript_file:
            prompt = args.prompt or Path(args.transcript_file).read_text(encoding="utf-8")
            response = conversation.respond(session, prompt, mode=mode)
            print_chat_response(response)
            return 0
        return run_chat_loop(conversation, session, mode)

    if args.command == "flywheel":
        if args.flywheel_command == "stats":
            print_json(app.intent_library.stats(), default=str)
            return 0
        if args.flywheel_command == "templates":
            templates = [
                {
                    "intent_id": template.intent_id,
                    "intent_label": template.intent_label,
                    "status": template.status,
                    "hit_count": template.hit_count,
                    "success_rate": template.success_rate,
                    "example_count": len(template.example_inputs),
                    "correction_count": template.correction_count,
                    "missing_info_count": template.missing_info_count,
                    "view_type": template.view_type,
                    "updated_at": template.updated_at.isoformat(),
                }
                for template in app.intent_library.all()
                if args.status is None or template.status == args.status
            ]
            templates.sort(key=lambda item: item["updated_at"], reverse=True)
            print_json(templates[: args.limit], default=str)
            return 0
        if args.flywheel_command == "feedback":
            print_json(app.intent_library.feedback_events(signal=args.signal, limit=args.limit), default=str)
            return 0
        if args.flywheel_command == "review-queue":
            print_json(app.intent_library.review_queue(limit=args.limit), default=str)
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


def print_csv_rows(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    fieldnames = [
        "tenant_id",
        "client_id",
        "deadline_id",
        "tax_type",
        "jurisdiction",
        "due_date",
        "status",
        "override_date",
        "snoozed_until",
        "reminder_type",
    ]
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def serialize(value):
    if is_dataclass(value):
        return asdict(value)
    return value


def print_chat_response(response) -> None:
    print(response.reply)
    print("")
    for block in response.render_blocks:
        print(f"[{block.title}]")
        if not block.items:
            print("  (empty)")
            print("")
            continue
        for item in block.items:
            print(f"  - {json.dumps(item, ensure_ascii=True, sort_keys=True)}")
        print("")


def run_chat_loop(conversation, session, mode: InteractionMode) -> int:
    print("DueDateHQ interactive mode. Type 'exit' to leave.")
    print("")
    while True:
        try:
            prompt = input(f"{mode.value}> ").strip()
        except EOFError:
            print("")
            return 0
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            return 0
        response = conversation.respond(session, prompt, mode=mode)
        print_chat_response(response)


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
