from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.flywheel_router import FlywheelIntentRouter
from duedatehq.core.intent_cache import InMemoryIntentLibrary


class CountingPlanner:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = 0

    def plan(self, text, session):
        self.calls += 1
        return self.wrapped.plan(text, session)

    def is_confirm(self, text):
        return self.wrapped.is_confirm(text)

    def is_cancel(self, text):
        return self.wrapped.is_cancel(text)


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "flywheel-router.sqlite3"))


def _seed_router_data(app):
    tenant = app.engine.create_tenant("Tenant A")
    today = datetime.now(timezone.utc).date()
    app.engine.create_rule(
        tax_type="sales_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=2)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://example.com/rule",
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
    return {
        "tenant_id": tenant.tenant_id,
        "today": today.isoformat(),
        "session_id": "session-1",
        "selectable_items": [
            {
                "ref": "item_1",
                "deadline_id": deadline.deadline_id,
                "client_id": client.client_id,
                "client_name": client.name,
            }
        ],
        "client_names": [client.name],
    }


def test_flywheel_router_learns_then_serves_similar_input_from_cache(app):
    session = _seed_router_data(app)
    planner = CountingPlanner(app.intent_planner)
    router = FlywheelIntentRouter(intent_library=InMemoryIntentLibrary(), planner=planner)

    first = router.plan("今天先做什么", session)
    second = router.plan("今天最紧急的是什么", session)

    assert first["intent_label"] == "today"
    assert second["intent_label"] == "today"
    assert planner.calls == 1
    assert router.snapshot()["cache_hits"] == 1
    assert session["_last_plan_route"]["source"] == "cache"


def test_flywheel_router_falls_back_when_primary_fails(app):
    session = _seed_router_data(app)

    class BrokenPlanner(CountingPlanner):
        def plan(self, text, session):
            self.calls += 1
            raise RuntimeError("primary unavailable")

    primary = BrokenPlanner(app.intent_planner)
    fallback = CountingPlanner(app.intent_planner)
    router = FlywheelIntentRouter(
        intent_library=InMemoryIntentLibrary(),
        planner=primary,
        fallback_planner=fallback,
    )

    plan = router.plan("今天先做什么", session)

    assert plan["intent_label"] == "today"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert router.snapshot()["fallback_calls"] == 1
    assert session["_last_plan_route"]["source"] == "fallback"


def test_flywheel_router_learns_low_risk_guidance_intents(app):
    session = _seed_router_data(app)
    planner = CountingPlanner(app.intent_planner)
    router = FlywheelIntentRouter(intent_library=InMemoryIntentLibrary(), planner=planner)

    first = router.plan("help", session)
    second = router.plan("怎么用", session)

    assert first["intent_label"] == "help"
    assert second["intent_label"] == "help"
    assert planner.calls == 1
    assert router.snapshot()["cache_hits"] == 1
