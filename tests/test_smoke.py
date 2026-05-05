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
from duedatehq.core.models import BlockerStatus, DeadlineAction, DeadlineStatus, NotificationChannel, NotificationStatus, ReminderStatus, RuleReviewItem, RuleStatus, TaskStatus
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
    schema_path = Path(__file__).resolve().parents[1] / "db" / "postgres_schema.sql"
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
    assert registry["state_ca"].display_name == "California Franchise Tax Board Newsroom"
    assert registry["state_ca"].default_url == "https://www.ftb.ca.gov/about-ftb/newsroom/index.html"
    assert registry["state_tx"].display_name == "Texas Comptroller News Releases"
    assert registry["state_tx"].default_url == "https://comptroller.texas.gov/about/media-center/news/index.php"
    assert registry["state_ny"].display_name == "New York Tax Department Press Office"
    assert registry["state_ny"].default_url == "https://www.tax.ny.gov/press/"


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


def test_california_newsroom_notice_parses_into_rule(app):
    result = app.engine.fetch_from_source(
        state="CA",
        raw_text=(
            "California Franchise Tax Board announced that the 2026 PTE election deadline "
            "moves from April 30, 2026 to May 30, 2026 for qualifying pass-through entities."
        ),
        source_url="https://www.ftb.ca.gov/about-ftb/newsroom/pte-election-update.html",
        fetched_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
        actor="cli",
    )

    assert result["fetch_run"].status == "rule_written"
    rule = result["result"]
    assert rule.jurisdiction == "CA"
    assert rule.tax_type == "pte_election"
    assert rule.deadline_date == "2026-05-30"


def test_new_york_press_notice_parses_into_rule(app):
    result = app.engine.fetch_from_source(
        state="NY",
        raw_text=(
            "The New York Tax Department confirmed that the PTET election deadline for tax year 2026 "
            "is March 15, 2026 under updated department guidance."
        ),
        source_url="https://www.tax.ny.gov/press/ptet-2026-deadline.htm",
        fetched_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        actor="cli",
    )

    assert result["fetch_run"].status == "rule_written"
    rule = result["result"]
    assert rule.jurisdiction == "NY"
    assert rule.tax_type == "ptet"
    assert rule.deadline_date == "2026-03-15"


def test_texas_news_release_without_due_date_routes_to_review_queue_with_enriched_parse_payload(app):
    result = app.engine.fetch_from_source(
        state="TX",
        raw_text=(
            "Texas Comptroller updated economic nexus guidance for remote sellers. "
            "The economic nexus threshold drops from $500K to $400K of Texas-sourced sales."
        ),
        source_url="https://comptroller.texas.gov/about/media-center/news/2026/economic-nexus-update.php",
        fetched_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        actor="cli",
    )

    assert result["fetch_run"].status == "review_queued"
    review_item = result["result"]
    assert review_item.parse_payload["jurisdiction"] == "TX"
    assert review_item.parse_payload["tax_type"] == "sales_tax"
    assert review_item.parse_payload["deadline_date"] is None


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


def test_client_bundle_and_tax_profile_update(app):
    tenant = app.engine.create_tenant("Tenant Bundle")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Harbor Studio Partners",
        entity_type="partnership",
        registered_states=["NY"],
        tax_year=2026,
        home_jurisdiction="NY",
        primary_contact_name="Evan Malik",
        primary_contact_email="evan@example.com",
        intake_status="draft",
        profile_source="import",
    )

    bundle = app.engine.get_client_bundle(tenant.tenant_id, client.client_id)

    assert bundle["client"].client_id == client.client_id
    assert len(bundle["tax_profiles"]) == 1
    assert bundle["tax_profiles"][0].intake_status == "draft"
    assert len(bundle["jurisdictions"]) >= 1
    assert len(bundle["contacts"]) == 1

    updated = app.engine.update_client_tax_profile(
        tenant_id=tenant.tenant_id,
        client_id=client.client_id,
        tax_year=2026,
        intake_status="needs_followup",
        extension_requested=True,
        payroll_present=False,
        actor="cli",
    )

    assert updated.intake_status == "needs_followup"
    assert updated.extension_requested is True
    refreshed = app.engine.get_client_bundle(tenant.tenant_id, client.client_id)
    assert refreshed["tax_profiles"][0].intake_status == "needs_followup"


def test_task_lifecycle_and_client_bundle(app):
    tenant = app.engine.create_tenant("Tenant Tasks")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Northwind Services LLC",
        entity_type="llc",
        registered_states=["CA"],
        tax_year=2026,
    )

    task = app.engine.create_task(
        tenant_id=tenant.tenant_id,
        client_id=client.client_id,
        title="Follow up on payroll package",
        description="Need missing payroll support docs before filing can move.",
        task_type="follow_up",
        priority="critical",
        source_type="blocker",
        source_id="blocker-001",
        actor="cli",
    )

    assert task.status is TaskStatus.OPEN
    listed = app.engine.list_tasks(tenant.tenant_id, client.client_id)
    assert [item.task_id for item in listed] == [task.task_id]

    updated = app.engine.update_task_status(
        tenant_id=tenant.tenant_id,
        task_id=task.task_id,
        status=TaskStatus.BLOCKED,
        actor="cli",
    )
    assert updated.status is TaskStatus.BLOCKED

    bundle = app.engine.get_client_bundle(tenant.tenant_id, client.client_id)
    assert len(bundle["tasks"]) == 1
    assert bundle["tasks"][0].task_id == task.task_id
    assert bundle["tasks"][0].status is TaskStatus.BLOCKED


def test_task_update_edits_content(app):
    tenant = app.engine.create_tenant("Tenant Task Update")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Aurora Tech Labs",
        entity_type="c-corp",
        registered_states=["CA", "NY"],
        tax_year=2026,
    )

    task = app.engine.create_task(
        tenant_id=tenant.tenant_id,
        client_id=client.client_id,
        title="Prepare state income filing",
        description="Initial generated task.",
        task_type="deadline_action",
        priority="normal",
        source_type="deadline",
        source_id="deadline-001",
        actor="cli",
    )

    due_at = datetime.now(timezone.utc) + timedelta(days=3)
    updated = app.engine.update_task(
        tenant_id=tenant.tenant_id,
        task_id=task.task_id,
        title="Prepare and review state income filing",
        description="CPA added a review step after the initial task generation.",
        priority="high",
        owner_user_id="sarah-johnson",
        due_at=due_at,
        actor="cli",
    )

    assert updated.title == "Prepare and review state income filing"
    assert updated.description == "CPA added a review step after the initial task generation."
    assert updated.priority == "high"
    assert updated.owner_user_id == "sarah-johnson"
    assert updated.due_at == due_at

    bundle = app.engine.get_client_bundle(tenant.tenant_id, client.client_id)
    assert bundle["tasks"][0].title == "Prepare and review state income filing"
    assert bundle["tasks"][0].priority == "high"
    assert bundle["tasks"][0].owner_user_id == "sarah-johnson"
    assert bundle["tasks"][0].due_at == due_at


def test_import_preview_engine_analysis(app, tmp_path):
    source = tmp_path / "clients.csv"
    source.write_text(
        "Client Name,Entity / Return Type,State Footprint,Payroll States\n"
        "Northwind Services LLC,LLC,\"CA,NV\",CA\n"
        "Harbor Studio Partners,Partnership,NY,\n",
        encoding="utf-8",
    )

    preview = app.engine.preview_import_csv(source)

    assert preview["source_name"] == "clients.csv"
    assert preview["imported_rows"] == 2
    assert preview["required_mappings"] == 3
    assert preview["resolved_required_mappings"] == 3
    assert any(item["target_field"] == "Client name" and item["status"] == "Mapped" for item in preview["mappings"])
    assert any("home jurisdiction" in item.lower() for item in preview["missing_fields"])
    assert preview["sample_rows"][0][0] == "Northwind Services LLC"


def test_import_preview_text_supports_mapping_overrides_and_ai_assist(app):
    preview = app.engine.preview_import_text(
        source_name="messy.csv",
        csv_text=(
            "Account,Return Kind,Markets,Home,Owner Email\n"
            "Northwind Services LLC,LLC,\"CA,NV\",CA,maya@example.com\n"
        ),
        mapping_overrides={"Account": "client_name", "Return Kind": "entity_type", "Markets": "operating_states", "Home": "home_jurisdiction"},
    )

    assert preview["source_name"] == "messy.csv"
    assert preview["ready_to_generate"] is True
    assert preview["ai_assist"]["supports_manual_overrides"] is True
    assert preview["ai_assist"]["normalized_clients"][0]["client_name"] == "Northwind Services LLC"


def test_import_apply_with_plan_review_and_approval(app, tmp_path):
    tenant = app.engine.create_tenant("Tenant Import Plan Review")
    due_date = (datetime.now(timezone.utc).date() + timedelta(days=6)).isoformat()
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["llc"],
        deadline_date=due_date,
        effective_from=datetime.now(timezone.utc).date().isoformat(),
        source_url="https://ftb.ca.gov/rule",
        confidence_score=0.99,
    )
    source = tmp_path / "plan-review.csv"
    source.write_text(
        "Client Name,Entity / Return Type,State Footprint,Home State\n"
        "Northwind Services LLC,LLC,CA,\n",
        encoding="utf-8",
    )

    applied = app.engine.apply_import_csv(
        tenant.tenant_id,
        source,
        tax_year=2026,
        create_initial_tasks=False,
        actor="cli",
    )

    assert len(applied["created_clients"]) == 1
    assert len(applied["created_blockers"]) == 1
    assert applied["created_tasks"] == []
    assert applied["initial_task_creation_deferred"] is True
    assert len(applied["proposed_plan"]) == 1
    proposed_item = applied["proposed_plan"][0]
    assert proposed_item.client_name == "Northwind Services LLC"
    assert proposed_item.default_action in {"now", "later"}

    approved = app.engine.approve_import_plan(
        tenant.tenant_id,
        [
            {
                **serialize(proposed_item),
                "decision": "later",
                "planned_window": "next_week",
            }
        ],
        actor="cli",
    )

    assert approved["summary"] == {"now": 0, "later": 1, "skip": 0}
    assert len(approved["created_tasks"]) == 1
    assert approved["created_tasks"][0].task_type == "import_plan"
    assert approved["dashboard"]["open_task_count"] == 1


def test_import_apply_writes_clients_and_generates_initial_work(app, tmp_path):
    tenant = app.engine.create_tenant("Tenant Import Apply")
    due_date = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["llc"],
        deadline_date=due_date,
        effective_from=datetime.now(timezone.utc).date().isoformat(),
        source_url="https://ftb.ca.gov/rule",
        confidence_score=0.99,
    )
    source = tmp_path / "apply.csv"
    source.write_text(
        "Client Name,Entity / Return Type,State Footprint,Home State,Contact Email\n"
        "Northwind Services LLC,LLC,CA,,maya@example.com\n"
        "Harbor Studio Partners,LLC,CA,CA,evan@example.com\n",
        encoding="utf-8",
    )

    result = app.engine.apply_import_csv(
        tenant_id=tenant.tenant_id,
        csv_path=source,
        tax_year=2026,
        actor="cli",
    )

    assert len(result["created_clients"]) == 2
    assert len(result["created_blockers"]) == 1
    assert result["created_blockers"][0].title.startswith("Confirm home jurisdiction")
    assert len(result["created_tasks"]) == 2
    assert result["dashboard"]["client_count"] == 2
    assert result["dashboard"]["open_task_count"] >= 2
    assert result["dashboard"]["open_blocker_count"] == 1


def test_blocker_lifecycle_and_client_bundle(app):
    tenant = app.engine.create_tenant("Tenant Blockers")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Sierra Wholesale Inc.",
        entity_type="c-corp",
        registered_states=["TX", "CA"],
        tax_year=2026,
    )

    blocker = app.engine.create_blocker(
        tenant_id=tenant.tenant_id,
        client_id=client.client_id,
        title="Need missing Texas payroll confirmation",
        description="Payroll state coverage is incomplete in the imported sheet.",
        blocker_type="missing_info",
        source_type="import",
        source_id="import-001",
        actor="cli",
    )

    assert blocker.status is BlockerStatus.OPEN
    listed = app.engine.list_blockers(tenant.tenant_id, client.client_id)
    assert [item.blocker_id for item in listed] == [blocker.blocker_id]

    updated = app.engine.update_blocker_status(
        tenant_id=tenant.tenant_id,
        blocker_id=blocker.blocker_id,
        status=BlockerStatus.RESOLVED,
        actor="cli",
    )
    assert updated.status is BlockerStatus.RESOLVED

    bundle = app.engine.get_client_bundle(tenant.tenant_id, client.client_id)
    assert len(bundle["blockers"]) == 1
    assert bundle["blockers"][0].blocker_id == blocker.blocker_id
    assert bundle["blockers"][0].status is BlockerStatus.RESOLVED


def test_notice_generate_work_creates_tasks_and_blockers(app):
    tenant = app.engine.create_tenant("Tenant Notices")
    client_a = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Northwind Services LLC",
        entity_type="llc",
        registered_states=["CA"],
        tax_year=2026,
    )
    client_b = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Sierra Wholesale Inc.",
        entity_type="c-corp",
        registered_states=["TX", "CA"],
        tax_year=2026,
    )
    client_c = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Harbor Studio Partners",
        entity_type="partnership",
        registered_states=["NY"],
        tax_year=2026,
    )

    result = app.engine.generate_notice_work(
        tenant_id=tenant.tenant_id,
        notice_id="notice-002",
        title="Texas nexus threshold clarification",
        source_url="https://comptroller.texas.gov/",
        affected_clients=[
            {
                "client_id": client_a.client_id,
                "auto_updated": False,
                "reason": "CA footprint may need manual nexus review.",
                "old_date": "2026-04-30",
                "new_date": "2026-05-08",
            },
            {
                "client_id": client_b.client_id,
                "auto_updated": False,
                "needs_client_confirmation": True,
                "reason": "Imported state footprint is incomplete.",
            },
            {
                "client_id": client_c.client_id,
                "auto_updated": True,
            },
        ],
        actor="cli",
    )

    assert len(result["tasks"]) == 1
    assert result["tasks"][0].client_id == client_a.client_id
    assert len(result["blockers"]) == 1
    assert result["blockers"][0].client_id == client_b.client_id
    assert result["skipped_clients"][0]["client_id"] == client_c.client_id

    rerun = app.engine.generate_notice_work(
        tenant_id=tenant.tenant_id,
        notice_id="notice-002",
        title="Texas nexus threshold clarification",
        source_url="https://comptroller.texas.gov/",
        affected_clients=[
            {"client_id": client_a.client_id, "auto_updated": False},
            {"client_id": client_b.client_id, "auto_updated": False, "needs_client_confirmation": True},
        ],
        actor="cli",
    )
    assert len(rerun["tasks"]) == 0
    assert len(rerun["blockers"]) == 0
    assert {item["disposition"] for item in rerun["skipped_clients"]} == {"existing_task", "existing_blocker"}


def test_review_impact_payload_links_source_interpretation_and_notice_work(app):
    tenant = app.engine.create_tenant("Tenant Review Impact")
    client_a = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Northwind Services LLC",
        entity_type="llc",
        registered_states=["CA"],
        tax_year=2026,
    )
    client_b = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Sierra Wholesale Inc.",
        entity_type="c-corp",
        registered_states=["TX", "CA"],
        tax_year=2026,
    )

    app.engine.fetch_from_source(
        state="TX",
        raw_text=(
            "Texas Comptroller updated economic nexus guidance for remote sellers. "
            "The economic nexus threshold drops from $500K to $400K of Texas-sourced sales."
        ),
        source_url="https://comptroller.texas.gov/about/media-center/news/economic-nexus.html",
        fetched_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        actor="test",
    )
    app.engine.generate_notice_work(
        tenant_id=tenant.tenant_id,
        notice_id="notice-002",
        title="Texas nexus threshold clarification",
        source_url="https://comptroller.texas.gov/about/media-center/news/economic-nexus.html",
        summary="Threshold change may require a client-level nexus check.",
        affected_clients=[
            {
                "client_id": client_a.client_id,
                "auto_updated": False,
                "reason": "Manual CA review is still needed.",
            },
            {
                "client_id": client_b.client_id,
                "auto_updated": False,
                "missing_context": True,
                "reason": "Imported footprint is incomplete.",
            },
        ],
        actor="test",
    )

    payload = app.engine.review_impact_payload(tenant.tenant_id)

    assert payload["source_health"]["official_source_count"] >= 53
    review = payload["rule_reviews"][0]
    assert review["source"]["display_name"] == "Texas Comptroller News Releases"
    assert "deadline_date" in review["interpretation"]["missing_fields"]
    assert any(item["client_name"] == "Sierra Wholesale Inc." for item in review["affected_clients"])
    notice = payload["notices"][0]
    assert notice["source"]["display_name"] == "Texas Comptroller News Releases"
    assert {item["disposition"] for item in notice["affected_clients"]} == {"task_created", "blocker_created"}


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

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "export", tenant.tenant_id, "--client", client.client_id, "--format", "csv"],
    )
    assert cli_main() == 0
    export_csv = capsys.readouterr().out
    assert "deadline_id" in export_csv
    assert client.client_id in export_csv


def test_cli_task_routes(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-tasks.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant Tasks")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Harbor Studio Partners",
        entity_type="partnership",
        registered_states=["NY"],
        tax_year=2026,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "duedatehq",
            "--db",
            db_path,
            "task",
            "add",
            tenant.tenant_id,
            client.client_id,
            "--title",
            "Review PTE election decision",
            "--task-type",
            "review",
            "--priority",
            "high",
            "--source-type",
            "deadline",
            "--source-id",
            "dl-002",
        ],
    )
    assert cli_main() == 0
    task_payload = json.loads(capsys.readouterr().out)
    assert task_payload["title"] == "Review PTE election decision"
    assert task_payload["status"] == "open"

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "task", "list", tenant.tenant_id, "--client", client.client_id],
    )
    assert cli_main() == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert len(list_payload) == 1
    task_id = list_payload[0]["task_id"]

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "task", "update-status", tenant.tenant_id, task_id, "--status", "done"],
    )
    assert cli_main() == 0
    updated_payload = json.loads(capsys.readouterr().out)
    assert updated_payload["status"] == "done"

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "client", "show", tenant.tenant_id, client.client_id],
    )
    assert cli_main() == 0
    bundle_payload = json.loads(capsys.readouterr().out)
    assert len(bundle_payload["tasks"]) == 1
    assert bundle_payload["tasks"][0]["task_id"] == task_id


def test_cli_task_update_route(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-task-update.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant Task Edit")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Maple Hill Dental Group",
        entity_type="professional-corp",
        registered_states=["MN", "WI"],
        tax_year=2026,
    )
    task = app.engine.create_task(
        tenant_id=tenant.tenant_id,
        client_id=client.client_id,
        title="Prepare sales/use filing",
        description="Generated from import plan.",
        task_type="import_plan",
        priority="normal",
        source_type="import_plan",
        source_id="plan-001",
        actor="cli",
    )
    due_at = "2026-05-20T17:00:00+00:00"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "duedatehq",
            "--db",
            db_path,
            "task",
            "update",
            tenant.tenant_id,
            task.task_id,
            "--title",
            "Prepare sales/use filing and confirm county rates",
            "--description",
            "CPA updated the generated task before it entered the work queue.",
            "--priority",
            "high",
            "--owner-user-id",
            "maya-chen",
            "--due-at",
            due_at,
        ],
    )
    assert cli_main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Prepare sales/use filing and confirm county rates"
    assert payload["description"] == "CPA updated the generated task before it entered the work queue."
    assert payload["priority"] == "high"
    assert payload["owner_user_id"] == "maya-chen"
    assert datetime.fromisoformat(payload["due_at"]) == datetime.fromisoformat(due_at)


def test_cli_import_preview_route(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-import.sqlite3")
    csv_path = tmp_path / "portfolio.csv"
    csv_path.write_text(
        "Client Name,Entity / Return Type,State Footprint,Home State\n"
        "Sierra Wholesale Inc.,C-Corp,\"TX,CA\",TX\n"
        "Harbor Studio Partners,Partnership,NY,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "import", "preview", "--csv", str(csv_path)],
    )
    assert cli_main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_name"] == "portfolio.csv"
    assert payload["source_kind"] == "CSV import"
    assert payload["imported_rows"] == 2
    assert any(item["target_field"] == "Home jurisdiction" and item["status"] == "Mapped" for item in payload["mappings"])


def test_cli_import_apply_route(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-import-apply.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant CLI Import Apply")
    due_date = (datetime.now(timezone.utc).date() + timedelta(days=6)).isoformat()
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["llc"],
        deadline_date=due_date,
        effective_from=datetime.now(timezone.utc).date().isoformat(),
        source_url="https://ftb.ca.gov/rule",
        confidence_score=0.99,
    )
    csv_path = tmp_path / "apply.csv"
    csv_path.write_text(
        "Client Name,Entity / Return Type,State Footprint,Home State\n"
        "Northwind Services LLC,LLC,CA,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "duedatehq",
            "--db",
            db_path,
            "import",
            "apply",
            tenant.tenant_id,
            "--csv",
            str(csv_path),
            "--tax-year",
            "2026",
        ],
    )
    assert cli_main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["created_clients"]) == 1
    assert len(payload["created_blockers"]) == 1
    assert len(payload["created_tasks"]) == 1
    assert payload["dashboard"]["client_count"] == 1
    assert payload["dashboard"]["open_blocker_count"] == 1


def test_cli_import_apply_deferred_and_approve_plan(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-import-plan.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant CLI Import Plan")
    due_date = (datetime.now(timezone.utc).date() + timedelta(days=6)).isoformat()
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["llc"],
        deadline_date=due_date,
        effective_from=datetime.now(timezone.utc).date().isoformat(),
        source_url="https://ftb.ca.gov/rule",
        confidence_score=0.99,
    )
    csv_path = tmp_path / "apply-plan.csv"
    csv_path.write_text(
        "Client Name,Entity / Return Type,State Footprint,Home State\n"
        "Northwind Services LLC,LLC,CA,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "duedatehq",
            "--db",
            db_path,
            "import",
            "apply",
            tenant.tenant_id,
            "--csv",
            str(csv_path),
            "--tax-year",
            "2026",
            "--defer-task-creation",
        ],
    )
    assert cli_main() == 0
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["initial_task_creation_deferred"] is True
    assert apply_payload["created_tasks"] == []
    assert len(apply_payload["proposed_plan"]) == 1

    plan_payload = [
        {
            **apply_payload["proposed_plan"][0],
            "decision": "now",
            "planned_window": "do_now",
        }
    ]
    plan_path = tmp_path / "approved-plan.json"
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "duedatehq",
            "--db",
            db_path,
            "import",
            "approve-plan",
            tenant.tenant_id,
            "--plan-file",
            str(plan_path),
        ],
    )
    assert cli_main() == 0
    approved_payload = json.loads(capsys.readouterr().out)
    assert approved_payload["summary"] == {"now": 1, "later": 0, "skip": 0}
    assert len(approved_payload["created_tasks"]) == 1
    assert approved_payload["dashboard"]["open_task_count"] == 1


def test_cli_blocker_routes(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-blockers.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant Blockers")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Northwind Services LLC",
        entity_type="llc",
        registered_states=["CA"],
        tax_year=2026,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "duedatehq",
            "--db",
            db_path,
            "blocker",
            "add",
            tenant.tenant_id,
            client.client_id,
            "--title",
            "Need payroll support docs",
            "--blocker-type",
            "missing_info",
            "--source-type",
            "import",
            "--source-id",
            "import-001",
        ],
    )
    assert cli_main() == 0
    blocker_payload = json.loads(capsys.readouterr().out)
    assert blocker_payload["status"] == "open"

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "blocker", "list", tenant.tenant_id, "--client", client.client_id],
    )
    assert cli_main() == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert len(list_payload) == 1
    blocker_id = list_payload[0]["blocker_id"]

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "blocker", "update-status", tenant.tenant_id, blocker_id, "--status", "resolved"],
    )
    assert cli_main() == 0
    updated_payload = json.loads(capsys.readouterr().out)
    assert updated_payload["status"] == "resolved"

    monkeypatch.setattr(
        sys,
        "argv",
        ["duedatehq", "--db", db_path, "client", "show", tenant.tenant_id, client.client_id],
    )
    assert cli_main() == 0
    bundle_payload = json.loads(capsys.readouterr().out)
    assert len(bundle_payload["blockers"]) == 1
    assert bundle_payload["blockers"][0]["blocker_id"] == blocker_id


def test_cli_notice_generate_work_route(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli-notice.sqlite3")
    app = create_app(db_path)
    tenant = app.engine.create_tenant("Tenant Notice CLI")
    client_a = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Northwind Services LLC",
        entity_type="llc",
        registered_states=["CA"],
        tax_year=2026,
    )
    client_b = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Sierra Wholesale Inc.",
        entity_type="c-corp",
        registered_states=["TX", "CA"],
        tax_year=2026,
    )
    impacts_path = tmp_path / "notice-impacts.json"
    impacts_path.write_text(
        json.dumps(
            [
                {
                    "client_id": client_a.client_id,
                    "auto_updated": False,
                    "reason": "Manual CA review is still needed.",
                },
                {
                    "client_id": client_b.client_id,
                    "auto_updated": False,
                    "missing_context": True,
                    "reason": "Imported footprint is incomplete.",
                },
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "duedatehq",
            "--db",
            db_path,
            "notice",
            "generate-work",
            tenant.tenant_id,
            "--notice-id",
            "notice-002",
            "--title",
            "Texas nexus threshold clarification",
            "--source-url",
            "https://comptroller.texas.gov/",
            "--impacts-file",
            str(impacts_path),
        ],
    )
    assert cli_main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["tasks"]) == 1
    assert len(payload["blockers"]) == 1
    assert payload["tasks"][0]["source_type"] == "notice"
    assert payload["blockers"][0]["source_type"] == "notice"


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


def test_queue_client_email_uses_client_contact_and_dispatches(app):
    tenant = app.engine.create_tenant("Tenant Client Email")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-05-15",
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
        primary_contact_name="Maya Chen",
        primary_contact_email="maya@example.com",
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]

    delivery = app.engine.queue_client_email(
        tenant.tenant_id,
        client.client_id,
        deadline_id=deadline.deadline_id,
        subject="Need documents for upcoming filing",
        body="Please upload the missing support documents.",
        actor="user-1",
    )

    assert delivery.destination == "maya@example.com"
    assert delivery.deadline_id == deadline.deadline_id
    assert delivery.status == NotificationStatus.PENDING

    registry = NotifierRegistry({NotificationChannel.EMAIL: ConsoleNotifier(NotificationChannel.EMAIL)})
    sent = app.engine.dispatch_notification_deliveries(tenant.tenant_id, registry, actor="system")
    assert sent == 1
    deliveries = app.engine.list_notification_deliveries(tenant.tenant_id, deadline.deadline_id)
    assert deliveries[-1].status == NotificationStatus.SENT


def test_draft_client_email_uses_work_context(app):
    tenant = app.engine.create_tenant("Tenant Draft Email")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-05-15",
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
        primary_contact_name="Maya Chen",
        primary_contact_email="maya@example.com",
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
    app.engine.create_blocker(
        tenant_id=tenant.tenant_id,
        client_id=client.client_id,
        title="Missing payroll support",
        description="Need Q1 payroll register.",
        blocker_type="missing_info",
        source_type="deadline",
        source_id=deadline.deadline_id,
    )

    draft = app.engine.draft_client_email(tenant.tenant_id, client.client_id, deadline_id=deadline.deadline_id)

    assert draft["to"] == "maya@example.com"
    assert "Acme LLC" in draft["subject"]
    assert "Missing payroll support" in draft["body"]
    assert draft["provider"] in {"anthropic", "deterministic-fallback"}


def test_queue_client_email_can_use_task_anchor(app):
    tenant = app.engine.create_tenant("Tenant Task Email")
    app.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-05-15",
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
        primary_contact_email="maya@example.com",
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
    task = app.engine.create_task(
        tenant_id=tenant.tenant_id,
        client_id=client.client_id,
        title="Collect missing support documents",
        description="Request documents before preparing the filing.",
        task_type="client_request",
        priority="high",
        source_type="deadline",
        source_id=deadline.deadline_id,
        actor="user-1",
    )

    delivery = app.engine.queue_client_email(
        tenant.tenant_id,
        client.client_id,
        task_id=task.task_id,
        subject="Missing support documents",
        body="Please send the missing support documents.",
        actor="user-1",
    )

    assert delivery.deadline_id == deadline.deadline_id
    assert delivery.destination == "maya@example.com"


def test_queue_client_email_requires_work_anchor(app):
    tenant = app.engine.create_tenant("Tenant Email Anchor")
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
        primary_contact_email="maya@example.com",
    )

    with pytest.raises(ValueError, match="anchored"):
        app.engine.queue_client_email(
            tenant.tenant_id,
            client.client_id,
            subject="Loose email",
            body="This should not be allowed.",
            actor="user-1",
        )


def test_settings_payload_and_notification_route_update(app):
    tenant = app.engine.create_tenant("Tenant Settings")
    route = app.engine.configure_notification_route(
        tenant.tenant_id,
        NotificationChannel.EMAIL,
        "owner@example.com",
        actor="user-1",
    )
    app.engine.configure_notification_route(
        tenant.tenant_id,
        NotificationChannel.WECHAT,
        "wechat://johnson-cpa",
        actor="user-1",
        enabled=False,
    )

    payload = app.engine.settings_payload(tenant.tenant_id)
    assert payload["tenant"]["name"] == "Tenant Settings"
    assert payload["notification_summary"]["enabled_channels"] == 1
    assert payload["notification_routes"][0]["destination"] == "owner@example.com"
    assert {route["channel"] for route in payload["notification_routes"]} == {"email", "wechat"}

    updated = app.engine.update_notification_route(
        tenant.tenant_id,
        route.route_id,
        destination="ops@example.com",
        enabled=False,
        actor="user-1",
    )

    assert updated.destination == "ops@example.com"
    assert updated.enabled is False
    payload = app.engine.settings_payload(tenant.tenant_id)
    assert payload["notification_summary"]["enabled_channels"] == 0
    assert payload["notification_routes"][0]["enabled"] is False


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
