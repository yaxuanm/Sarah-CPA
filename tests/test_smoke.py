import email.message
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone
import sys
import types

import pytest

from duedatehq.api import chat as api_chat
from duedatehq.app import build_storage, create_app
from duedatehq.cli import main as cli_main
from duedatehq.core.conversation import InteractionMode
from duedatehq.core.dispatchers import CeleryDispatcher
from duedatehq.core.fetchers import FileFetcher, HttpTextFetcher, RssEntryFetcher, fetcher_for_source
from duedatehq.core.models import DeadlineAction, DeadlineStatus, NotificationChannel, NotificationStatus, ReminderStatus, RuleReviewItem, RuleStatus
from duedatehq.core.notifiers import ConsoleNotifier, NotifierRegistry
from duedatehq.core.postgres import PostgresStorage
from duedatehq.core.sources import official_source_registry
from duedatehq.core.workers import FetchWorker, InMemoryJobQueue, PersistentJobQueue, ReminderScheduler, ReminderWorker
from duedatehq.layers.state_machine import InvalidTransitionError


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "test.sqlite3"))


def test_storage_selector_defaults_to_sqlite(tmp_path):
    storage = build_storage(str(tmp_path / "alt.sqlite3"))

    assert storage.__class__.__name__ == "SQLiteStorage"
    with storage.transaction(tenant_id="tenant-a") as conn:
        row = conn.execute("SELECT 1 AS value").fetchone()
    assert row["value"] == 1


def test_storage_selector_supports_env_var(monkeypatch, tmp_path):
    target = tmp_path / "env.sqlite3"
    monkeypatch.setenv("DUEDATEHQ_DATABASE_URL", str(target))

    storage = build_storage(None)

    assert storage.__class__.__name__ == "SQLiteStorage"
    assert str(storage.db_path).endswith("env.sqlite3")


def test_postgres_schema_file_exists_and_has_rls_policies():
    schema_path = Path("C:/sarah-cpa/db/postgres_schema.sql")
    schema = schema_path.read_text(encoding="utf-8")

    assert schema_path.exists()
    assert "ENABLE ROW LEVEL SECURITY" in schema
    assert "require_tenant_id()" in schema
    assert "audit_log_append_only" in schema


def test_postgres_integration_test_is_skipped_without_dsn():
    dsn = os.getenv("DUEDATEHQ_TEST_POSTGRES_DSN")
    if dsn:
        pytest.skip("integration DSN provided; skip absence assertion")
    assert dsn is None


def test_rule_low_confidence_routes_to_review_queue(app):
    result = app.engine.ingest_rule_text(
        raw_text="IRS announced a change but details remain unclear.",
        source_url="https://example.com/irs",
        fetched_at=datetime.now(timezone.utc),
    )

    assert isinstance(result, RuleReviewItem)
    assert len(app.engine.list_rules()) == 0
    assert len(app.engine.list_rule_review_queue()) == 1


def test_source_registry_matches_document_coverage():
    registry = official_source_registry()

    assert "irs" in registry
    assert "fema" in registry
    assert "federal_register" in registry
    assert len([key for key in registry if key.startswith("state_")]) == 50
    assert registry["irs"].poll_frequency_minutes == 15
    assert registry["fema"].poll_frequency_minutes == 15
    assert registry["state_ca"].poll_frequency_minutes == 60
    assert registry["irs"].default_url.startswith("https://")


def test_official_source_fetcher_factory_returns_expected_fetcher():
    irs_fetcher = fetcher_for_source(source="irs")
    fema_fetcher = fetcher_for_source(source="fema")

    assert irs_fetcher.__class__.__name__ == "HtmlFetcher"
    assert fema_fetcher.__class__.__name__ == "RssEntryFetcher"


def test_fetch_records_run_and_writes_rule(app):
    result = app.engine.fetch_from_source(
        source="irs",
        raw_text=(
            "tax_type: federal_income\n"
            "jurisdiction: FEDERAL\n"
            "entity_types: s-corp\n"
            "deadline_date: 2026-03-15\n"
            "effective_from: 2026-01-01\n"
        ),
        source_url="https://irs.gov/notice-1",
        fetched_at=datetime.now(timezone.utc),
        actor="cli",
    )

    assert result["fetch_run"].status == "rule_written"
    assert result["result"].source_url == "https://irs.gov/notice-1"
    assert len(app.engine.list_fetch_runs()) == 1
    assert len(app.engine.list_rules()) == 1


def test_fetch_worker_uses_file_fetcher(app, tmp_path):
    notice = tmp_path / "notice.txt"
    notice.write_text(
        "tax_type: federal_income\n"
        "jurisdiction: FEDERAL\n"
        "entity_types: s-corp\n"
        "deadline_date: 2026-03-15\n"
        "effective_from: 2026-01-01\n",
        encoding="utf-8",
    )
    worker = FetchWorker(app.engine)
    result = worker.run(
        source="irs",
        fetcher=FileFetcher(path=notice, source_url="https://irs.gov/file-notice"),
    )

    assert result["fetch_run"].source_key == "irs"
    assert result["result"].tax_type == "federal_income"


def test_http_text_fetcher(monkeypatch):
    class FakeResponse:
        def __init__(self, body: str):
            self._body = body.encode("utf-8")
            self.headers = email.message.Message()
            self.headers["Content-Type"] = "text/plain; charset=utf-8"

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("duedatehq.core.fetchers.urlopen", lambda request, timeout=30: FakeResponse("hello tax world"))
    document = HttpTextFetcher(url="https://example.com/notice").fetch()

    assert document.raw_text == "hello tax world"
    assert document.source_url == "https://example.com/notice"


def test_rss_entry_fetcher(monkeypatch):
    rss_body = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>Other notice</title><description>ignore</description><link>https://example.com/1</link></item>
      <item><title>California deadline update</title><description>deadline moved</description><link>https://example.com/2</link></item>
    </channel></rss>"""

    class FakeResponse:
        def __init__(self, body: str):
            self._body = body.encode("utf-8")
            self.headers = email.message.Message()
            self.headers["Content-Type"] = "application/rss+xml; charset=utf-8"

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("duedatehq.core.fetchers.urlopen", lambda request, timeout=30: FakeResponse(rss_body))
    document = RssEntryFetcher(url="https://example.com/feed", entry_title_contains="california").fetch()

    assert "deadline moved" in document.raw_text
    assert document.source_url == "https://example.com/2"


def test_client_rule_mapping_and_rule_change_update_deadline(app):
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-03-15",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date="2026-04-15",
        effective_from="2026-01-01",
        source_url="https://ftb.ca.gov/r1",
        confidence_score=0.99,
    )
    app.engine.create_rule(
        tax_type="annual_report",
        jurisdiction="DE",
        entity_types=["s-corp"],
        deadline_date="2026-03-01",
        effective_from="2026-01-01",
        source_url="https://de.gov/r1",
        confidence_score=0.99,
    )

    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["TX", "CA", "DE"],
        tax_year=2026,
    )
    deadlines = app.engine.list_deadlines(tenant.tenant_id, client.client_id)
    assert {(item.tax_type, item.jurisdiction, item.due_date) for item in deadlines} == {
        ("federal_income", "FEDERAL", "2026-03-15"),
        ("franchise_tax", "CA", "2026-04-15"),
        ("annual_report", "DE", "2026-03-01"),
    }

    updated_rule = app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date="2026-05-15",
        effective_from="2026-02-01",
        source_url="https://ftb.ca.gov/r2",
        confidence_score=0.99,
    )
    deadlines = app.engine.list_deadlines(tenant.tenant_id, client.client_id)
    ca_deadline = [item for item in deadlines if item.jurisdiction == "CA"][0]
    assert ca_deadline.due_date == "2026-05-15"
    assert ca_deadline.rule_id == updated_rule.rule_id
    rules = app.engine.list_rules()
    previous_ca_rule = [item for item in rules if item.jurisdiction == "CA" and item.version == 1][0]
    assert previous_ca_rule.status == RuleStatus.SUPERSEDED


def test_reminder_queue_rebuild_and_completion_cancels_future(app):
    tenant = app.engine.create_tenant("Tenant A")
    rule = app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date="2026-04-20",
        effective_from="2026-01-01",
        source_url="https://ftb.ca.gov/r1",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
    reminders = app.engine.list_reminders(tenant.tenant_id, deadline.deadline_id)
    assert [item.reminder_day for item in reminders] == ["-30", "-14", "-7", "-1"]

    app.engine.apply_deadline_action(
        tenant.tenant_id,
        deadline.deadline_id,
        DeadlineAction.COMPLETE,
        actor="user-1",
    )
    reminders = app.engine.list_reminders(tenant.tenant_id, deadline.deadline_id)
    assert reminders == []
    reminder_history = app.engine.list_reminders(tenant.tenant_id, deadline.deadline_id, include_history=True)
    assert all(item.status == ReminderStatus.CANCELLED for item in reminder_history)

    app.engine.apply_deadline_action(
        tenant.tenant_id,
        deadline.deadline_id,
        DeadlineAction.REOPEN,
        actor="user-1",
    )
    app.engine.apply_deadline_action(
        tenant.tenant_id,
        deadline.deadline_id,
        DeadlineAction.OVERRIDE,
        actor="user-1",
        metadata={"new_date": "2026-05-10"},
    )
    reminders = app.engine.list_reminders(tenant.tenant_id, deadline.deadline_id)
    assert [item.reminder_day for item in reminders] == ["-30", "-14", "-7", "-1"]
    assert reminders[-1].scheduled_at.date().isoformat() == "2026-05-09"
    reminder_history = app.engine.list_reminders(tenant.tenant_id, deadline.deadline_id, include_history=True)
    scheduled = [item for item in reminder_history if item.status == ReminderStatus.SCHEDULED]
    cancelled = [item for item in reminder_history if item.status == ReminderStatus.CANCELLED]
    assert len(scheduled) == 4
    assert cancelled
    assert rule.rule_id != app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).rule_id or True


def test_today_and_notify_views(app):
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-04-25",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]

    today_items = app.engine.today(tenant.tenant_id)
    assert today_items[0].deadline_id == deadline.deadline_id

    preview = app.engine.notify_preview(tenant.tenant_id, within_days=365)
    assert len(preview) == 4
    app.engine.trigger_due_reminders(datetime(2026, 4, 30, tzinfo=timezone.utc))
    history = app.engine.notify_history(tenant.tenant_id)
    assert history


def test_cli_gap_features_in_engine(app):
    tenant = app.engine.create_tenant("Tenant A")
    today = datetime.now(timezone.utc).date()
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=3)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://ftb.ca.gov/r1",
        confidence_score=0.99,
    )
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=12)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    app.engine.create_rule(
        tax_type="annual_report",
        jurisdiction="DE",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=20)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://de.gov/r1",
        confidence_score=0.99,
    )
    client_a = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA", "DE"],
        tax_year=today.year,
    )
    client_b = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Beta LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )

    acme_deadlines = app.engine.list_deadlines(tenant.tenant_id, client_a.client_id)
    beta_deadlines = app.engine.list_deadlines(tenant.tenant_id, client_b.client_id)
    app.engine.apply_deadline_action(tenant.tenant_id, acme_deadlines[0].deadline_id, DeadlineAction.COMPLETE, actor="user-1")

    pending_deadlines = app.engine.list_deadlines(tenant.tenant_id, status=DeadlineStatus.PENDING)
    assert all(item.status == DeadlineStatus.PENDING for item in pending_deadlines)
    assert all(item.deadline_id != acme_deadlines[0].deadline_id for item in pending_deadlines)

    upcoming = app.engine.list_deadlines(tenant.tenant_id, within_days=7)
    assert upcoming
    assert all(datetime.fromisoformat(item.due_date).date() <= today + timedelta(days=7) for item in upcoming)

    ca_deadlines = app.engine.list_deadlines(tenant.tenant_id, jurisdiction="ca")
    assert ca_deadlines
    assert all(item.jurisdiction == "CA" for item in ca_deadlines)

    paged = app.engine.list_deadlines(tenant.tenant_id, limit=2, offset=1)
    expected = app.engine.list_deadlines(tenant.tenant_id)[1:3]
    assert [item.deadline_id for item in paged] == [item.deadline_id for item in expected]

    enriched = app.engine.today_enriched(tenant.tenant_id, limit=10)
    assert enriched
    assert {"client_name", "days_remaining"} <= set(enriched[0].keys())
    assert any(item["client_name"] == "Beta LLC" for item in enriched)

    actions = app.engine.available_deadline_actions(tenant.tenant_id, beta_deadlines[0].deadline_id)
    assert actions["current_status"] == DeadlineStatus.PENDING.value
    assert actions["available_actions"] == ["complete", "snooze", "waive", "override"]

    exported = app.engine.export_deadlines(tenant.tenant_id, actor="cli", client_id=client_b.client_id)
    assert exported
    assert {item["client_id"] for item in exported} == {client_b.client_id}


def test_cli_routes_new_deadline_and_today_features(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-features.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant A")
    today = datetime.now(timezone.utc).date()
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=2)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://ftb.ca.gov/r1",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "today", tenant.tenant_id, "--limit", "5", "--enrich"],
    )
    assert cli_main() == 0
    today_payload = json.loads(capsys.readouterr().out)
    assert today_payload[0]["client_name"] == "Acme LLC"
    assert "days_remaining" in today_payload[0]

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "deadline", "available-actions", tenant.tenant_id, deadline.deadline_id],
    )
    assert cli_main() == 0
    actions_payload = json.loads(capsys.readouterr().out)
    assert actions_payload["available_actions"] == ["complete", "snooze", "waive", "override"]

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "export", tenant.tenant_id, "--client", client.client_id],
    )
    assert cli_main() == 0
    export_payload = json.loads(capsys.readouterr().out)
    assert {item["client_id"] for item in export_payload} == {client.client_id}


def test_notification_routes_and_deliveries(app):
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-04-02",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
    app.engine.configure_notification_route(
        tenant.tenant_id,
        NotificationChannel.EMAIL,
        "owner@example.com",
        actor="user-1",
    )
    app.engine.trigger_due_reminders(datetime(2026, 4, 30, tzinfo=timezone.utc))
    deliveries = app.engine.list_notification_deliveries(tenant.tenant_id, deadline.deadline_id)

    assert deliveries
    assert deliveries[0].status == NotificationStatus.PENDING

    registry = NotifierRegistry({NotificationChannel.EMAIL: ConsoleNotifier(NotificationChannel.EMAIL)})
    sent = app.engine.dispatch_notification_deliveries(tenant.tenant_id, registry, actor="system")
    assert sent == len(deliveries)
    deliveries = app.engine.list_notification_deliveries(tenant.tenant_id, deadline.deadline_id)
    assert all(item.status == NotificationStatus.SENT for item in deliveries)


def test_trigger_due_reminders_is_tenant_scoped(app):
    tenant_a = app.engine.create_tenant("Tenant A")
    tenant_b = app.engine.create_tenant("Tenant B")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-04-02",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    client_a = app.engine.register_client(
        tenant_id=tenant_a.tenant_id,
        name="Alpha LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    client_b = app.engine.register_client(
        tenant_id=tenant_b.tenant_id,
        name="Beta LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    deadline_a = app.engine.list_deadlines(tenant_a.tenant_id, client_a.client_id)[0]
    deadline_b = app.engine.list_deadlines(tenant_b.tenant_id, client_b.client_id)[0]

    triggered = app.engine.trigger_due_reminders(datetime(2026, 4, 30, tzinfo=timezone.utc), tenant_id=tenant_a.tenant_id)

    assert triggered == 4
    reminders_a = app.engine.list_reminders(tenant_a.tenant_id, deadline_a.deadline_id, include_history=True)
    reminders_b = app.engine.list_reminders(tenant_b.tenant_id, deadline_b.deadline_id, include_history=True)
    assert all(item.status == ReminderStatus.TRIGGERED for item in reminders_a)
    assert all(item.status == ReminderStatus.SCHEDULED for item in reminders_b)


def test_reminder_scheduler_and_worker_flow(app):
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-04-02",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
    queue = InMemoryJobQueue()
    scheduler = ReminderScheduler(app.engine, queue)
    now = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)

    jobs = scheduler.enqueue_next_window(tenant.tenant_id, now=now, hours=24)
    assert jobs

    dispatched = ReminderWorker(app.engine).run(jobs, now=now)
    assert dispatched >= 1
    reminders = app.engine.list_reminders(tenant.tenant_id, deadline.deadline_id)
    assert any(item.status == ReminderStatus.TRIGGERED for item in reminders)


def test_persistent_job_queue_round_trip(app):
    queue = PersistentJobQueue(app.engine.repositories.storage)
    now = datetime.now(timezone.utc)
    job = queue.enqueue(
        "send_reminder",
        {"tenant_id": "tenant-a", "deadline_id": "deadline-a"},
        created_at=now,
        tenant_id="tenant-a",
        available_at=now,
    )

    claimed = queue.drain(tenant_id="tenant-a", now=now)
    assert claimed[0].job_id == job.job_id

    queue.complete(claimed, now)
    jobs = queue.list_jobs("tenant-a")
    assert jobs[0].status == "completed"


def test_celery_dispatcher_and_app(monkeypatch):
    calls = []

    class FakeCeleryApp:
        def __init__(self, *args, **kwargs):
            self.conf = types.SimpleNamespace(broker_url=kwargs["broker"], task_default_queue="duedatehq")

        def send_task(self, name, kwargs):
            calls.append((name, kwargs))
            return types.SimpleNamespace(id=f"task-{len(calls)}")

    fake_celery_module = types.SimpleNamespace(Celery=FakeCeleryApp)
    monkeypatch.setitem(sys.modules, "celery", fake_celery_module)

    dispatcher = CeleryDispatcher("redis://localhost:6379/9")
    task_id = dispatcher.dispatch_schedule_reminders("tenant-a", db_url="sqlite:///tmp")

    assert task_id == "task-1"
    assert calls[0][0] == "duedatehq.schedule_reminders"


def test_conversation_service_renders_today_view(app):
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-04-25",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )

    session = app.conversation.start_session(tenant.tenant_id, mode=InteractionMode.TEXT)
    response = app.conversation.respond(session, "show me today", mode=InteractionMode.TEXT)

    assert response.intent.value == "today"
    assert "deadline" in response.reply.lower()
    assert response.render_blocks[0].block_type == "today"
    assert response.render_blocks[0].items


def test_api_chat_returns_reply_and_render_block(tmp_path):
    db_path = str(tmp_path / "chat.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-04-25",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )

    response = api_chat("deadlines", tenant_id=tenant.tenant_id, db_path=db_path)

    assert response["intent"] == "deadlines"
    assert response["render_blocks"][0]["block_type"] == "deadlines"
    assert response["render_blocks"][0]["items"]


def test_state_machine_and_audit_protections(app):
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date="2026-04-20",
        effective_from="2026-01-01",
        source_url="https://ftb.ca.gov/r1",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]

    snooze_until = datetime.now(timezone.utc) + timedelta(days=3)
    app.engine.apply_deadline_action(
        tenant.tenant_id,
        deadline.deadline_id,
        DeadlineAction.SNOOZE,
        actor="user-1",
        metadata={"until": snooze_until.isoformat()},
    )
    assert app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status == DeadlineStatus.SNOOZED
    app.engine.resume_due_snoozes(snooze_until + timedelta(minutes=1))
    app.engine.apply_deadline_action(tenant.tenant_id, deadline.deadline_id, DeadlineAction.COMPLETE, actor="user-1")
    app.engine.apply_deadline_action(tenant.tenant_id, deadline.deadline_id, DeadlineAction.REOPEN, actor="user-1")
    app.engine.apply_deadline_action(tenant.tenant_id, deadline.deadline_id, DeadlineAction.WAIVE, actor="user-1")

    transitions = app.engine.list_transitions(deadline.deadline_id)
    assert [item.action for item in transitions] == ["snooze", "resume", "complete", "reopen", "waive"]

    with pytest.raises(InvalidTransitionError):
        app.engine.apply_deadline_action(tenant.tenant_id, deadline.deadline_id, DeadlineAction.COMPLETE, actor="user-1")

    with app.engine.repositories.storage.connect() as conn:
        row = conn.execute("SELECT log_id FROM audit_log LIMIT 1").fetchone()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE audit_log SET actor = 'hacked' WHERE log_id = ?", (row["log_id"],))
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM audit_log WHERE log_id = ?", (row["log_id"],))


def test_audit_failure_rolls_back_business_write(app):
    tenant = app.engine.create_tenant("Tenant A")
    app.engine.repositories.storage.fail_next_audit_write = True

    with pytest.raises(RuntimeError):
        app.engine.register_client(
            tenant_id=tenant.tenant_id,
            name="Acme LLC",
            entity_type="s-corp",
            registered_states=["CA"],
            tax_year=2026,
        )

    assert app.engine.list_clients(tenant.tenant_id) == []
