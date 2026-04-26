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


def test_interaction_backend_message_renders_today_and_remembers_selectable_items(app):
    _, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_message("今天先做什么", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ListCard"
    assert session["selectable_items"][0]["deadline_id"]
    assert session["current_view"]["type"] == "ListCard"


def test_interaction_backend_message_focuses_client_by_name(app):
    _, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_message("先看 Acme", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_name"] == "Acme LLC"


def test_interaction_backend_message_requires_confirmation_before_write(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    app.interaction_backend.process_message("今天先做什么", session)
    confirm = app.interaction_backend.process_message("完成第一条", session)

    assert confirm["view"]["type"] == "ConfirmCard"
    assert session["pending_action_plan"]["op_class"] == "write"
    assert app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value == "pending"

    done = app.interaction_backend.process_message("确认", session)

    assert done["status"] == "ok"
    assert "pending_action_plan" not in session
    assert app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value == "completed"


def test_interaction_backend_resolves_cross_turn_reference_from_today_to_current_item(app):
    _, _, _, session = _seed_interaction_data(app)

    today = app.interaction_backend.process_message("今天先做什么", session)
    focused = app.interaction_backend.process_message("看第一条", session)
    selectable_after_focus = list(session["selectable_items"])
    history = app.interaction_backend.process_message("刚才那个为什么变了", session)
    confirm = app.interaction_backend.process_message("完成这个", session)

    assert today["view"]["type"] == "ListCard"
    assert focused["view"]["type"] == "ClientCard"
    assert history["view"]["type"] == "HistoryCard"
    assert session["selectable_items"] == selectable_after_focus
    assert confirm["view"]["type"] == "ConfirmCard"
    assert session["pending_action_plan"]["op_class"] == "write"


def test_interaction_backend_can_cancel_and_resume_cross_turn_write(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    app.interaction_backend.process_message("先看 Acme", session)
    app.interaction_backend.process_message("这个来源是什么", session)
    first_confirm = app.interaction_backend.process_message("完成当前这个", session)
    cancelled = app.interaction_backend.process_message("取消", session)
    second_confirm = app.interaction_backend.process_message("完成刚才那个", session)
    before = app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value
    done = app.interaction_backend.process_message("确认", session)
    after = app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value

    assert first_confirm["view"]["type"] == "ConfirmCard"
    assert cancelled["view"]["type"] == "GuidanceCard"
    assert "pending_action_plan" not in session
    assert second_confirm["view"]["type"] == "ConfirmCard"
    assert before == "pending"
    assert done["view"]["type"] == "ListCard"
    assert after == "completed"
