from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.models import DeadlineAction


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "on-demand-contract.sqlite3"))


def _seed_contract_data(app):
    tenant = app.engine.create_tenant("Tenant A")
    today = datetime.now(timezone.utc).date()
    app.engine.create_rule(
        tax_type="sales_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=1)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://tax.ca.gov/sales-tax",
        confidence_score=0.99,
    )
    app.engine.create_rule(
        tax_type="annual_report",
        jurisdiction="DE",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=7)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://de.gov/annual-report",
        confidence_score=0.99,
    )
    acme = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA", "DE"],
        tax_year=today.year,
    )
    greenway = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Greenway Consulting LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    session = {
        "tenant_id": tenant.tenant_id,
        "today": today.isoformat(),
        "session_id": "contract-session",
        "client_names": [acme.name, greenway.name],
    }
    return tenant, acme, greenway, session


def test_today_need_renders_prioritized_list_with_only_decision_facts(app):
    _, _, _, session = _seed_contract_data(app)

    response = app.interaction_backend.process_message("今天先做什么", session)

    assert session["last_turn"]["intent_label"] == "today"
    assert response["view"]["type"] == "ListCard"
    assert response["view"]["data"]["items"]
    first_item = response["view"]["data"]["items"][0]
    for field in ["deadline_id", "client_id", "client_name", "tax_type", "due_date", "status", "days_remaining"]:
        assert field in first_item
    assert len(response["actions"]) <= 3
    assert all("another" not in action["label"].casefold() for action in response["actions"])
    assert all(action["plan"]["op_class"] == "write" for action in response["actions"])


def test_client_need_renders_client_card_without_cross_task_shortcuts(app):
    _, acme, _, session = _seed_contract_data(app)

    response = app.interaction_backend.process_message("先看 Acme", session)

    assert session["last_turn"]["intent_label"] == "client_deadline_list"
    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_name"] == "Acme LLC"
    assert response["view"]["data"]["deadlines"]
    assert {item["client_id"] for item in response["view"]["data"]["deadlines"]} == {acme.client_id}
    assert {item["client_id"] for item in response["view"]["selectable_items"]} == {acme.client_id}
    action_deadline_ids = {action["plan"]["plan"][0]["args"]["deadline_id"] for action in response["actions"]}
    assert action_deadline_ids <= {response["view"]["data"]["deadlines"][0]["deadline_id"]}


def test_write_need_renders_confirmation_and_explains_consequence_before_mutating(app):
    tenant, _, _, session = _seed_contract_data(app)
    app.interaction_backend.process_message("今天先做什么", session)
    target = session["selectable_items"][0]

    response = app.interaction_backend.process_message("完成第一条", session)

    assert response["view"]["type"] == "ConfirmCard"
    assert response["view"]["data"]["consequence"]
    assert "改动" in response["view"]["data"]["consequence"]
    assert session["pending_action_plan"]["op_class"] == "write"
    assert app.engine.get_deadline(tenant.tenant_id, target["deadline_id"]).status.value == "pending"


def test_source_need_renders_history_card_with_source_not_generic_panel(app):
    _, _, _, session = _seed_contract_data(app)
    app.interaction_backend.process_message("今天先做什么", session)
    selected = session["selectable_items"][0]

    response = app.interaction_backend.process_message("这个来源是什么", session)

    assert session["last_turn"]["intent_label"] == "deadline_history"
    assert response["view"]["type"] == "HistoryCard"
    assert response["view"]["data"]["deadline_id"] == selected["deadline_id"]
    assert response["view"]["data"]["source_url"]
    assert "source_url" in response["view"]["data"]
    assert response["view"]["selectable_items"][0]["deadline_id"] == selected["deadline_id"]
    assert response["actions"] == []


def test_upcoming_and_completed_needs_render_deadline_lists(app):
    tenant, acme, _, session = _seed_contract_data(app)
    completed_deadline = app.engine.list_deadlines(tenant.tenant_id, acme.client_id)[0]
    app.engine.apply_deadline_action(
        tenant.tenant_id,
        completed_deadline.deadline_id,
        DeadlineAction.COMPLETE,
        actor="test",
    )

    upcoming = app.interaction_backend.process_message("未来30天有什么", session)
    completed = app.interaction_backend.process_message("已完成的有哪些", session)

    assert upcoming["view"]["type"] == "ListCard"
    assert "未来" in upcoming["view"]["data"]["title"]
    assert "suggested_prompts" in upcoming["view"]["data"]
    assert upcoming["view"]["data"]["items"]
    assert all(item["status"] != "completed" for item in upcoming["view"]["data"]["items"])
    assert upcoming["actions"] == []

    assert completed["view"]["type"] == "ListCard"
    assert completed["view"]["data"]["items"]
    assert {item["status"] for item in completed["view"]["data"]["items"]} == {"completed"}
    assert completed["actions"] == []


def test_notification_need_renders_reminder_preview_with_delivery_context(app):
    _, _, _, session = _seed_contract_data(app)

    response = app.interaction_backend.process_message("通知预览", session)

    assert response["view"]["type"] == "ReminderPreviewCard"
    assert response["view"]["data"]["reminders"]
    first = response["view"]["data"]["reminders"][0]
    for field in ["reminder_id", "deadline_id", "client_id", "client_name", "scheduled_at", "due_date", "tax_type"]:
        assert field in first
    assert response["actions"] == []


def test_client_list_need_renders_client_list_card(app):
    _, acme, greenway, session = _seed_contract_data(app)

    response = app.interaction_backend.process_message("客户列表", session)

    assert response["view"]["type"] == "ClientListCard"
    assert response["view"]["data"]["total"] == 2
    assert {client["client_id"] for client in response["view"]["data"]["clients"]} == {
        acme.client_id,
        greenway.client_id,
    }
    assert response["actions"] == []


def test_rule_review_need_renders_review_queue_card(app):
    _, _, _, session = _seed_contract_data(app)
    app.engine.ingest_rule_text(
        raw_text="A state tax update was mentioned, but no due date could be parsed.",
        source_url="https://example.com/unclear-rule",
        fetched_at=datetime.now(timezone.utc),
    )

    response = app.interaction_backend.process_message("规则审核队列", session)

    assert response["view"]["type"] == "ReviewQueueCard"
    assert response["view"]["data"]["items"]
    first = response["view"]["data"]["items"][0]
    for field in ["review_id", "source_url", "raw_text", "confidence_score"]:
        assert field in first
    assert response["actions"] == []
