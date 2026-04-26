from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.intent_cache import InMemoryIntentLibrary


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "intent-cache.sqlite3"))


def _seed_cache_data(app):
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
    session = {
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
    }
    return tenant, client, deadline, session


def test_intent_library_learns_and_matches_similar_today_input(app):
    _, _, _, session = _seed_cache_data(app)
    library = InMemoryIntentLibrary()
    plan = app.intent_planner.plan("今天先做什么", session)

    template = library.learn("今天先做什么", plan, session)
    match = library.match("今天最紧急的是什么", session)

    assert template.intent_label == "today"
    assert match is not None
    assert match.template.intent_label == "today"
    assert match.plan["plan"][0]["args"]["tenant_id"] == session["tenant_id"]


def test_intent_library_abstracts_relative_write_target(app):
    _, _, deadline, session = _seed_cache_data(app)
    library = InMemoryIntentLibrary()
    plan = app.intent_planner.plan("完成第一条", session)

    library.learn("完成第一条", plan, session)
    match = library.match("mark first done", session)

    assert match is not None
    assert match.plan["op_class"] == "write"
    assert match.plan["plan"][0]["args"]["deadline_id"] == deadline.deadline_id
