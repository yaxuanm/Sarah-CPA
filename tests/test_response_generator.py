from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.response_generator import ResponseGenerator


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "response.sqlite3"))


def _seed_response_data(app):
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
    app.engine.create_rule(
        tax_type="annual_report",
        jurisdiction="DE",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=8)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://de.gov/r1",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA", "DE"],
        tax_year=today.year,
    )
    return tenant, client, today.isoformat()


def test_response_generator_builds_today_list_card(app):
    tenant, _, today_value = _seed_response_data(app)
    generator = ResponseGenerator(app.engine)
    executor_result = {
        "intent_label": "today",
        "op_class": "read",
        "final_data": app.engine.today_enriched(tenant.tenant_id, limit=10),
    }

    response = generator.generate(executor_result, {"tenant_id": tenant.tenant_id, "today": today_value})

    assert response["view"]["type"] == "ListCard"
    assert response["view"]["data"]["items"]
    assert response["view"]["selectable_items"][0]["ref"] == "item_1"
    assert response["actions"]


def test_response_generator_adds_client_names_to_plain_deadlines(app):
    tenant, client, today_value = _seed_response_data(app)
    generator = ResponseGenerator(app.engine)
    deadlines = [generator._serialize_deadline(item) for item in app.engine.list_deadlines(tenant.tenant_id, client.client_id)]
    executor_result = {
        "intent_label": "today",
        "op_class": "read",
        "final_data": deadlines,
    }

    response = generator.generate(executor_result, {"tenant_id": tenant.tenant_id, "today": today_value})

    assert response["view"]["type"] == "ListCard"
    assert response["view"]["data"]["items"][0]["client_name"] == "Acme LLC"
    assert response["view"]["selectable_items"][0]["client_name"] == "Acme LLC"


def test_response_generator_builds_client_card_with_available_actions(app):
    tenant, client, today_value = _seed_response_data(app)
    generator = ResponseGenerator(app.engine)
    deadlines = [generator._serialize_deadline(item) for item in app.engine.list_deadlines(tenant.tenant_id, client.client_id)]
    executor_result = {
        "intent_label": "client_deadline_list",
        "op_class": "read",
        "final_data": deadlines,
    }

    response = generator.generate(executor_result, {"tenant_id": tenant.tenant_id, "today": today_value})

    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_name"] == "Acme LLC"
    assert response["view"]["data"]["deadlines"][0]["available_actions"]
    assert response["actions"][0]["plan"]["op_class"] == "write"


def test_response_generator_builds_client_card_from_client_bundle(app):
    tenant, client, today_value = _seed_response_data(app)
    generator = ResponseGenerator(app.engine)
    bundle = app.engine.get_client_bundle(tenant.tenant_id, client.client_id)
    executor_result = {
        "intent_label": "client_deadline_list",
        "op_class": "read",
        "final_data": bundle,
    }

    response = generator.generate(executor_result, {"tenant_id": tenant.tenant_id, "today": today_value})

    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_name"] == "Acme LLC"
    assert len(response["view"]["data"]["deadlines"]) == 2


def test_response_generator_ignores_non_deadline_values_in_client_response(app):
    tenant, client, today_value = _seed_response_data(app)
    generator = ResponseGenerator(app.engine)
    deadline = generator._serialize_deadline(app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0])
    executor_result = {
        "intent_label": "client_deadline_list",
        "op_class": "read",
        "final_data": {"client": generator._serialize_client(client), "deadlines": [deadline, "not-a-deadline"]},
    }

    response = generator.generate(executor_result, {"tenant_id": tenant.tenant_id, "today": today_value})

    assert response["view"]["type"] == "ClientCard"
    assert len(response["view"]["data"]["deadlines"]) == 1


def test_response_generator_builds_confirm_card_for_write_plan(app):
    tenant, client, _ = _seed_response_data(app)
    generator = ResponseGenerator(app.engine)
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
    plan = {
        "plan": [
            {
                "step_id": "s1",
                "type": "cli_call",
                "cli_group": "deadline",
                "cli_command": "action",
                "args": {
                    "tenant_id": tenant.tenant_id,
                    "deadline_id": deadline.deadline_id,
                    "action": "complete",
                },
            }
        ],
        "op_class": "write",
        "intent_label": "deadline_action_complete",
    }

    response = generator.generate_confirm_card(plan, {"tenant_id": tenant.tenant_id})

    assert response["view"]["type"] == "ConfirmCard"
    assert response["view"]["selectable_items"][0]["deadline_id"] == deadline.deadline_id
    assert response["view"]["data"]["options"][0]["plan"]["op_class"] == "write"


def test_response_generator_builds_guidance_card(app):
    generator = ResponseGenerator(app.engine)

    response = generator.generate_guidance(
        "没太理解。你是想——",
        ["查看今天的待处理事项", "查一个具体客户的情况"],
        [{"label": "Acme LLC", "ref": "item_1"}],
    )

    assert response["view"]["type"] == "GuidanceCard"
    assert response["view"]["data"]["context_options"][0]["ref"] == "item_1"
