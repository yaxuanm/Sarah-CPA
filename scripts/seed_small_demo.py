from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from duedatehq.app import create_app
from duedatehq.core.models import DeadlineAction, NotificationChannel


DEMO_TENANT_NAME = "Sarah Demo Tenant"


def _find_existing_tenant_id(db_path: str, tenant_name: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT tenant_id FROM tenants WHERE name = ?", (tenant_name,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def main() -> None:
    db_path = str(Path.cwd() / ".duedatehq" / "duedatehq.sqlite3")
    existing_tenant_id = _find_existing_tenant_id(db_path, DEMO_TENANT_NAME)
    if existing_tenant_id:
        print(
            json.dumps(
                {
                    "status": "exists",
                    "tenant_name": DEMO_TENANT_NAME,
                    "tenant_id": existing_tenant_id,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    app = create_app(db_path)
    engine = app.engine

    tenant = engine.create_tenant(DEMO_TENANT_NAME)

    engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-04-25",
        effective_from="2026-01-01",
        source_url="https://irs.gov/demo/federal-income",
        confidence_score=0.99,
    )
    engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date="2026-05-15",
        effective_from="2026-01-01",
        source_url="https://ftb.ca.gov/demo/franchise-tax",
        confidence_score=0.99,
    )
    engine.create_rule(
        tax_type="annual_report",
        jurisdiction="DE",
        entity_types=["s-corp"],
        deadline_date="2026-05-01",
        effective_from="2026-01-01",
        source_url="https://corp.delaware.gov/demo/annual-report",
        confidence_score=0.99,
    )
    engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="TX",
        entity_types=["s-corp"],
        deadline_date="2026-05-15",
        effective_from="2026-01-01",
        source_url="https://comptroller.texas.gov/demo/franchise-tax",
        confidence_score=0.99,
    )

    acme = engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme Holdings LLC",
        entity_type="s-corp",
        registered_states=["CA", "DE"],
        tax_year=2026,
    )
    lone_pine = engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Lone Pine Ventures LLC",
        entity_type="s-corp",
        registered_states=["TX"],
        tax_year=2026,
    )
    pacific = engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Pacific Studio LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
    )

    acme_deadlines = engine.list_deadlines(tenant.tenant_id, acme.client_id)
    lone_pine_deadlines = engine.list_deadlines(tenant.tenant_id, lone_pine.client_id)
    pacific_deadlines = engine.list_deadlines(tenant.tenant_id, pacific.client_id)

    federal_deadline = next(item for item in acme_deadlines if item.jurisdiction == "FEDERAL")
    engine.apply_deadline_action(
        tenant.tenant_id,
        federal_deadline.deadline_id,
        DeadlineAction.COMPLETE,
        actor="demo-seed",
    )
    engine.apply_deadline_action(
        tenant.tenant_id,
        federal_deadline.deadline_id,
        DeadlineAction.REOPEN,
        actor="demo-seed",
    )

    tx_deadline = next(item for item in lone_pine_deadlines if item.jurisdiction == "TX")
    engine.apply_deadline_action(
        tenant.tenant_id,
        tx_deadline.deadline_id,
        DeadlineAction.OVERRIDE,
        actor="demo-seed",
        metadata={"new_date": "2026-05-20"},
    )

    ca_deadline = next(item for item in pacific_deadlines if item.jurisdiction == "CA")
    engine.apply_deadline_action(
        tenant.tenant_id,
        ca_deadline.deadline_id,
        DeadlineAction.SNOOZE,
        actor="demo-seed",
        metadata={"until": "2026-04-27T17:00:00+00:00"},
    )

    route = engine.configure_notification_route(
        tenant.tenant_id,
        NotificationChannel.EMAIL,
        "owner@example.com",
        actor="demo-seed",
    )

    summary = {
        "status": "created",
        "tenant_name": tenant.name,
        "tenant_id": tenant.tenant_id,
        "clients": [
            {"client_id": acme.client_id, "name": acme.name},
            {"client_id": lone_pine.client_id, "name": lone_pine.name},
            {"client_id": pacific.client_id, "name": pacific.name},
        ],
        "notification_route_id": route.route_id,
        "today_count": len(engine.today_enriched(tenant.tenant_id, limit=10)),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
