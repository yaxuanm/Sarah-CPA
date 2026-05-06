from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from duedatehq.app import create_app
from duedatehq.core.models import DeadlineAction, NotificationChannel


DEMO_TENANT_NAME = "Sarah Demo Tenant"
DEMO_TENANT_ID = os.environ.get("DUEDATEHQ_DEMO_TENANT_ID", "2403c5e1-85ac-4593-86cc-02f8d97a8d92")
SARAH_STORY_CLIENTS = [
    {
        "name": "Acme Dental LLC",
        "entity_type": "s-corp",
        "registered_states": ["CA"],
        "tax_year": 2026,
    },
    {
        "name": "Greenway Consulting LLC",
        "entity_type": "s-corp",
        "registered_states": ["CA", "TX"],
        "tax_year": 2026,
    },
    {
        "name": "Brighton Manufacturing LLC",
        "entity_type": "s-corp",
        "registered_states": ["TX", "DE"],
        "tax_year": 2026,
    },
]

DEMO_RULES = [
    {
        "tax_type": "federal_income",
        "jurisdiction": "FEDERAL",
        "entity_types": ["s-corp"],
        "deadline_date": "2026-04-25",
        "effective_from": "2026-01-01",
        "source_url": "https://irs.gov/demo/federal-income",
        "confidence_score": 0.99,
        "raw_text": "Demo rule: Federal income return due date for S corporations remains 2026-04-25 in this tenant dataset.",
    },
    {
        "tax_type": "franchise_tax",
        "jurisdiction": "CA",
        "entity_types": ["s-corp"],
        "deadline_date": "2026-05-15",
        "effective_from": "2026-01-01",
        "source_url": "https://ftb.ca.gov/demo/franchise-tax",
        "confidence_score": 0.99,
        "raw_text": "Demo rule: California franchise tax payment and reporting workflow should be reviewed for S corporations.",
    },
    {
        "tax_type": "annual_report",
        "jurisdiction": "DE",
        "entity_types": ["s-corp"],
        "deadline_date": "2026-05-01",
        "effective_from": "2026-01-01",
        "source_url": "https://corp.delaware.gov/demo/annual-report",
        "confidence_score": 0.99,
        "raw_text": "Demo rule: Delaware annual report due date for active corporations in this mock dataset.",
    },
    {
        "tax_type": "franchise_tax",
        "jurisdiction": "TX",
        "entity_types": ["s-corp"],
        "deadline_date": "2026-05-15",
        "effective_from": "2026-01-01",
        "source_url": "https://comptroller.texas.gov/demo/franchise-tax",
        "confidence_score": 0.99,
        "raw_text": "Demo rule: Texas franchise tax due date and nexus review signal for entities registered in Texas.",
    },
]

DEMO_NOTICE_SCENARIOS = [
    {
        "notice_id": "demo-irs-2026-relief",
        "title": "IRS disaster relief filing extension watch",
        "source_url": "https://irs.gov/demo/disaster-relief-extension",
        "source_label": "IRS demo notice",
        "summary": "Fictional demo notice: federal filing relief may apply to clients with affected operations; review pending federal income deadlines before marking complete.",
        "client_impacts": [
            {
                "name": "Acme Dental LLC",
                "reason": "Client has a federal income deadline due now; confirm whether the relief county applies before treating the deadline as routine.",
                "needs_client_confirmation": True,
            },
            {
                "name": "Greenway Consulting LLC",
                "reason": "Multi-state footprint may qualify for relief, but the client profile does not show affected-county detail.",
                "missing_context": True,
            },
        ],
    },
    {
        "notice_id": "demo-ca-pte-2026",
        "title": "California PTE elective tax payment reminder",
        "source_url": "https://ftb.ca.gov/demo/pte-elective-tax",
        "source_label": "CA FTB demo notice",
        "summary": "Fictional demo notice: California pass-through elective tax timing may affect S-corp clients with CA registrations.",
        "client_impacts": [
            {
                "name": "Acme Dental LLC",
                "reason": "CA S-corp client; prepare a short client question before deciding whether a payment is needed.",
                "old_date": "2026-05-15",
                "new_date": "2026-06-15",
            },
            {
                "name": "Pacific Studio LLC",
                "reason": "CA filing exists but the current deadline is snoozed; keep it visible in the monitoring surface.",
                "auto_updated": False,
            },
        ],
    },
    {
        "notice_id": "demo-tx-franchise-threshold",
        "title": "Texas franchise tax no-tax-due threshold clarification",
        "source_url": "https://comptroller.texas.gov/demo/no-tax-due-threshold",
        "source_label": "TX Comptroller demo notice",
        "summary": "Fictional demo notice: Texas threshold language may change whether a client needs a full franchise tax workup.",
        "client_impacts": [
            {
                "name": "Lone Pine Ventures LLC",
                "reason": "TX-only S-corp; confirm gross receipts before deciding whether the franchise return can be simplified.",
                "needs_client_confirmation": True,
            },
            {
                "name": "Brighton Manufacturing LLC",
                "reason": "Registered in TX and DE; review whether the TX filing can be narrowed before preparing the return.",
            },
        ],
    },
]

DEMO_REVIEW_SOURCES = [
    {
        "source_url": "https://ftb.ca.gov/demo/ambiguous-local-surcharge",
        "raw_text": "FTB update: local surcharge calculation may affect selected taxpayers. Effective date pending.",
    },
    {
        "source_url": "https://irs.gov/demo/partial-efile-waiver",
        "raw_text": "IRS notice: e-file waiver language changed for some exempt entities. Due date not stated.",
    },
]


def _find_existing_tenant_id(db_path: str, tenant_name: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tenants'"
        ).fetchone()
        if row is None:
            return None
        row = conn.execute("SELECT tenant_id FROM tenants WHERE name = ?", (tenant_name,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _ensure_fixed_demo_tenant(db_path: str, tenant_id: str, tenant_name: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tenants'"
        ).fetchone()
        if row is None:
            raise RuntimeError("Tenants table has not been initialized.")
        existing = conn.execute("SELECT tenant_id FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()
        if existing:
            return "exists"
        conn.execute(
            "INSERT INTO tenants (tenant_id, name, created_at, is_deleted, deleted_at) VALUES (?, ?, ?, 0, NULL)",
            (tenant_id, tenant_name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return "created"
    finally:
        conn.close()


def _ensure_demo_rules(engine) -> list[dict[str, str]]:
    existing_source_urls = {rule.source_url for rule in engine.list_rules()}
    created = []
    for rule in DEMO_RULES:
        if rule["source_url"] in existing_source_urls:
            continue
        created_rule = engine.create_rule(actor="demo-seed", **rule)
        created.append(
            {
                "rule_id": created_rule.rule_id,
                "jurisdiction": created_rule.jurisdiction,
                "tax_type": created_rule.tax_type,
                "deadline_date": created_rule.deadline_date,
            }
        )
    return created


def _ensure_demo_rule_reviews(engine) -> list[dict[str, str]]:
    existing_source_urls = {item.source_url for item in engine.list_rule_review_queue()}
    created = []
    for review in DEMO_REVIEW_SOURCES:
        if review["source_url"] in existing_source_urls:
            continue
        item = engine.ingest_rule_text(
            raw_text=review["raw_text"],
            source_url=review["source_url"],
            fetched_at=datetime.now(timezone.utc),
            actor="demo-seed",
        )
        if hasattr(item, "review_id"):
            created.append({"review_id": item.review_id, "source_url": item.source_url})
    return created


def _ensure_demo_notices(engine, tenant_id: str) -> dict[str, object]:
    clients_by_name = {client.name: client for client in engine.list_clients(tenant_id)}
    created_or_updated = []
    missing_clients = []

    for scenario in DEMO_NOTICE_SCENARIOS:
        notice_id = f"{tenant_id}:{scenario['notice_id']}"
        affected_clients = []
        for impact in scenario["client_impacts"]:
            client = clients_by_name.get(impact["name"])
            if client is None:
                missing_clients.append(impact["name"])
                continue
            payload = {
                key: value
                for key, value in impact.items()
                if key != "name"
            }
            payload["client_id"] = client.client_id
            affected_clients.append(payload)
        if not affected_clients:
            continue
        result = engine.generate_notice_work(
            tenant_id=tenant_id,
            notice_id=notice_id,
            title=scenario["title"],
            source_url=scenario["source_url"],
            source_label=scenario["source_label"],
            summary=scenario["summary"],
            affected_clients=affected_clients,
            actor="demo-seed",
        )
        created_or_updated.append(
            {
                "notice_id": result["notice_id"],
                "title": result["title"],
                "tasks": len(result["tasks"]),
                "blockers": len(result["blockers"]),
                "skipped": len(result["skipped_clients"]),
            }
        )

    return {
        "notices": created_or_updated,
        "missing_clients": sorted(set(missing_clients)),
    }


def _ensure_story_clients(engine, tenant_id: str) -> list[dict[str, str]]:
    existing_names = {client.name for client in engine.list_clients(tenant_id)}
    created_clients = []
    for client in SARAH_STORY_CLIENTS:
        if client["name"] in existing_names:
            continue
        created = engine.register_client(tenant_id=tenant_id, **client)
        created_clients.append({"client_id": created.client_id, "name": created.name})
    return created_clients


def _seed_tax_demo_data(engine, tenant_id: str) -> dict[str, object]:
    return {
        "added_story_clients": _ensure_story_clients(engine, tenant_id),
        "added_rules": _ensure_demo_rules(engine),
        "added_rule_reviews": _ensure_demo_rule_reviews(engine),
        "notice_seed": _ensure_demo_notices(engine, tenant_id),
        "notice_count": len(engine.list_notices(tenant_id, limit=100)),
        "rule_review_count": len(engine.list_rule_review_queue()),
    }


def main() -> None:
    db_path = str(Path.cwd() / ".duedatehq" / "duedatehq.sqlite3")
    app = create_app(db_path)
    engine = app.engine
    tenant_status = _ensure_fixed_demo_tenant(db_path, DEMO_TENANT_ID, DEMO_TENANT_NAME)
    existing_tenant_id = DEMO_TENANT_ID

    if tenant_status == "exists":
        seeded = _seed_tax_demo_data(engine, existing_tenant_id)
        print(
            json.dumps(
                {
                    "status": tenant_status,
                    "tenant_name": DEMO_TENANT_NAME,
                    "tenant_id": existing_tenant_id,
                    **seeded,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    _ensure_demo_rules(engine)

    acme = engine.register_client(
        tenant_id=existing_tenant_id,
        name="Acme Holdings LLC",
        entity_type="s-corp",
        registered_states=["CA", "DE"],
        tax_year=2026,
    )
    lone_pine = engine.register_client(
        tenant_id=existing_tenant_id,
        name="Lone Pine Ventures LLC",
        entity_type="s-corp",
        registered_states=["TX"],
        tax_year=2026,
    )
    pacific = engine.register_client(
        tenant_id=existing_tenant_id,
        name="Pacific Studio LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    story_clients = [
        engine.register_client(tenant_id=existing_tenant_id, **client)
        for client in SARAH_STORY_CLIENTS
    ]

    acme_deadlines = engine.list_deadlines(existing_tenant_id, acme.client_id)
    lone_pine_deadlines = engine.list_deadlines(existing_tenant_id, lone_pine.client_id)
    pacific_deadlines = engine.list_deadlines(existing_tenant_id, pacific.client_id)

    federal_deadline = next(item for item in acme_deadlines if item.jurisdiction == "FEDERAL")
    engine.apply_deadline_action(
        existing_tenant_id,
        federal_deadline.deadline_id,
        DeadlineAction.COMPLETE,
        actor="demo-seed",
    )
    engine.apply_deadline_action(
        existing_tenant_id,
        federal_deadline.deadline_id,
        DeadlineAction.REOPEN,
        actor="demo-seed",
    )

    tx_deadline = next(item for item in lone_pine_deadlines if item.jurisdiction == "TX")
    engine.apply_deadline_action(
        existing_tenant_id,
        tx_deadline.deadline_id,
        DeadlineAction.OVERRIDE,
        actor="demo-seed",
        metadata={"new_date": "2026-05-20"},
    )

    ca_deadline = next(item for item in pacific_deadlines if item.jurisdiction == "CA")
    engine.apply_deadline_action(
        existing_tenant_id,
        ca_deadline.deadline_id,
        DeadlineAction.SNOOZE,
        actor="demo-seed",
        metadata={"until": "2026-04-27T17:00:00+00:00"},
    )

    route = engine.configure_notification_route(
        existing_tenant_id,
        NotificationChannel.EMAIL,
        "owner@example.com",
        actor="demo-seed",
    )
    seeded = _seed_tax_demo_data(engine, existing_tenant_id)

    summary = {
        "status": "created",
        "tenant_name": DEMO_TENANT_NAME,
        "tenant_id": existing_tenant_id,
        "clients": [
            {"client_id": acme.client_id, "name": acme.name},
            {"client_id": lone_pine.client_id, "name": lone_pine.name},
            {"client_id": pacific.client_id, "name": pacific.name},
            *[
                {"client_id": client.client_id, "name": client.name}
                for client in story_clients
            ],
        ],
        "notification_route_id": route.route_id,
        "today_count": len(engine.today_enriched(existing_tenant_id, limit=10)),
        **seeded,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
