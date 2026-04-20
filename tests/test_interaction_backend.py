from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "interaction.sqlite3"))


def _seed_interaction_data(app):
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
    session = {"tenant_id": tenant.tenant_id, "today": today.isoformat(), "session_id": "session-1"}
    return tenant, client, deadline, session


def test_interaction_backend_processes_read_plan(app):
    tenant, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_plan(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "today",
                    "cli_command": "today",
                    "args": {"tenant_id": tenant.tenant_id, "limit": 5, "enrich": True},
                }
            ],
            "intent_label": "today",
            "op_class": "read",
        },
        session,
    )

    assert response["view"]["type"] == "ListCard"
    assert response["view"]["data"]["items"]


def test_interaction_backend_returns_confirm_card_for_write_plan(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_plan(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "action",
                    "args": {"tenant_id": tenant.tenant_id, "deadline_id": deadline.deadline_id, "action": "complete"},
                }
            ],
            "intent_label": "deadline_action_complete",
            "op_class": "write",
        },
        session,
    )

    assert response["view"]["type"] == "ConfirmCard"
    assert response["view"]["data"]["options"][0]["plan"]["op_class"] == "write"


def test_interaction_backend_processes_confirmed_action(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_action(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "action",
                    "args": {"tenant_id": tenant.tenant_id, "deadline_id": deadline.deadline_id, "action": "complete"},
                }
            ],
            "intent_label": "deadline_action_complete",
            "op_class": "write",
        },
        session,
    )

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ListCard"
    assert response["session_id"] == "session-1"


def test_interaction_backend_turns_entity_not_found_into_guidance(app):
    tenant, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_plan(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "resolve_entity",
                    "entity_name": "Missing LLC",
                    "entity_type": "client",
                    "args": {"tenant_id": tenant.tenant_id},
                    "match_field": "name",
                    "bind_as": "resolved_client",
                }
            ],
            "intent_label": "client_deadline_list",
            "op_class": "read",
        },
        session,
    )

    assert response["view"]["type"] == "GuidanceCard"
