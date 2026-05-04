from __future__ import annotations

from datetime import datetime, timedelta, timezone

from duedatehq.app import create_app
from duedatehq.core.secretary_envelope import envelope_from_response
from duedatehq.core.template_tools import TemplateRegistry


def main() -> None:
    app = create_app()
    tenant = app.engine.create_tenant("Edge Case Tenant")
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
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )

    cases: list[tuple[str, bool]] = []

    greeting = envelope_from_response(
        {"message": "你好！有什么需要我处理的？", "view": {"type": "GuidanceCard", "data": {}}}
    )
    cases.append(("ambiguous greeting stays chat-only", greeting["action"]["type"] == "none"))

    planner_result = app.intent_planner.plan(
        "现在有多少客户",
        {"tenant_id": tenant.tenant_id, "today": today.isoformat(), "session_id": "edge", "selectable_items": []},
    )
    cases.append(("client-count wording routes to client_list", planner_result.get("intent_label") == "client_list"))

    registry = TemplateRegistry()
    cases.append(("exact template hit", registry.resolve_template("client_list", {})["status"] == "hit"))
    patch = registry.resolve_template("deadline by assignee", {"assignee": "Maya", "period": "2026-05"})
    cases.append(("near template becomes patch", patch["status"] == "patch" and "assignee" in patch["diff"]["add_slots"]))
    miss = registry.resolve_template("build waterfall billing risk", {"metric": "billing"})
    cases.append(("far request goes to staging miss", miss["status"] == "miss" and miss["skeleton"]["staging"] is True))

    loop = app.template_tools.run_render_loop(
        intent="client_list",
        slots={},
        tenant_id=tenant.tenant_id,
        session={"today": today.isoformat(), "selectable_items": []},
        response_view={"type": "ClientListCard", "data": {}},
    )
    event = loop["render_event"]
    cases.append(("slot data fetched before dispatch", event["filled_slots"]["total"] == 1 and event["slot_sources"]["total"] == "db"))
    cases.append(("dispatch render creates render id", str(event["render_id"]).startswith("render_")))

    failures = [name for name, ok in cases if not ok]
    for name, ok in cases:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    if failures:
        raise SystemExit(f"edge-case failures: {', '.join(failures)}")


if __name__ == "__main__":
    main()
