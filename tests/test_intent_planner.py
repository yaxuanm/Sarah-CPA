from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "planner.sqlite3"))


def _seed_planner_data(app):
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


def test_rule_based_planner_builds_today_plan(app):
    tenant, _, _, session = _seed_planner_data(app)

    plan = app.intent_planner.plan("今天先做什么", session)

    assert plan["intent_label"] == "today"
    assert plan["op_class"] == "read"
    assert plan["plan"][0]["args"]["tenant_id"] == tenant.tenant_id


def test_rule_based_planner_builds_client_plan_from_name(app):
    _, client, _, session = _seed_planner_data(app)

    plan = app.intent_planner.plan("先看 Acme", session)

    assert plan["intent_label"] == "client_deadline_list"
    assert plan["plan"][0]["args"]["client_id"] == client.client_id


def test_rule_based_planner_routes_client_count_question(app):
    tenant, _, _, session = _seed_planner_data(app)

    plan = app.intent_planner.plan("现在有多少客户", session)

    assert plan["intent_label"] == "client_list"
    assert plan["op_class"] == "read"
    assert plan["plan"][0]["cli_group"] == "client"
    assert plan["plan"][0]["args"]["tenant_id"] == tenant.tenant_id


def test_rule_based_planner_opens_numbered_visible_item(app):
    _, _, _, session = _seed_planner_data(app)
    session["selectable_items"].append(
        {
            "ref": "item_2",
            "deadline_id": "deadline-2",
            "client_id": "client-2",
            "client_name": "Second LLC",
        }
    )

    plan = app.intent_planner.plan("打开第 2 条", session)

    assert plan["intent_label"] == "client_deadline_list"
    assert plan["plan"][0]["args"]["client_id"] == "client-2"


def test_rule_based_planner_builds_write_plan_from_relative_reference(app):
    _, _, deadline, session = _seed_planner_data(app)

    plan = app.intent_planner.plan("完成第一条", session)

    assert plan["intent_label"] == "deadline_action_complete"
    assert plan["op_class"] == "write"
    assert plan["plan"][0]["args"]["deadline_id"] == deadline.deadline_id


def test_rule_based_planner_does_not_guess_write_target(app):
    _, _, _, session = _seed_planner_data(app)
    session["selectable_items"] = []

    plan = app.intent_planner.plan("完成这个", session)

    assert plan["special"] == "reference_unresolvable"
