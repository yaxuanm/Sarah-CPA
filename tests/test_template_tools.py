from __future__ import annotations

from datetime import datetime, timedelta, timezone

from duedatehq.app import create_app
from duedatehq.core.template_tools import TemplateRegistry


def _seed(app):
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
    return tenant, client, today


def test_template_resolver_hit_patch_and_miss_paths():
    registry = TemplateRegistry()

    hit = registry.resolve_template("client_list", {})
    patch = registry.resolve_template("deadline by assignee", {"assignee": "Maya", "period": "2026-05"})
    miss = registry.resolve_template("build me a waterfall chart of billing risk", {"metric": "billing_risk"})

    assert hit["status"] == "hit"
    assert hit["template_id"] == "client_list"
    assert patch["status"] == "patch"
    assert patch["base_template_id"] == "deadline_view"
    assert "assignee" in patch["diff"]["add_slots"]
    assert miss["status"] == "miss"
    assert miss["staging_template_id"].startswith("staging_")
    assert miss["skeleton"]["staging"] is True


def test_template_tool_loop_fetches_slots_before_dispatch():
    app = create_app()
    tenant, _, today = _seed(app)

    result = app.template_tools.run_render_loop(
        intent="client_list",
        slots={},
        tenant_id=tenant.tenant_id,
        session={"today": today.isoformat(), "selectable_items": []},
        response_view={"type": "ClientListCard", "data": {}},
    )

    assert result["resolution"]["status"] == "hit"
    event = result["render_event"]
    assert event["template_id"] == "client_list"
    assert event["render_id"].startswith("render_")
    assert event["filled_slots"]["total"] == 1
    assert event["filled_slots"]["clients"][0]["name"] == "Acme LLC"
    assert event["slot_sources"] == {"clients": "db", "total": "db"}
