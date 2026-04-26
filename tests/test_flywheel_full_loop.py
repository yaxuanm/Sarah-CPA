from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.flywheel_router import FlywheelIntentRouter


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DUEDATEHQ_USE_FLYWHEEL_ROUTER", "1")
    monkeypatch.delenv("DUEDATEHQ_USE_CLAUDE_NLU", raising=False)
    return create_app(str(tmp_path / "flywheel-full-loop.sqlite3"))


def _seed_full_loop_data(app):
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
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA", "DE"],
        tax_year=today.year,
    )
    return {
        "tenant_id": tenant.tenant_id,
        "today": today.isoformat(),
        "session_id": "full-loop-session",
        "client_names": [client.name],
    }


def test_full_flywheel_loop_learns_renders_corrects_and_executes(app):
    session = _seed_full_loop_data(app)
    assert isinstance(app.intent_planner, FlywheelIntentRouter)

    first = app.interaction_backend.process_message("今天先做什么", session)
    first_template_id = session["last_turn"]["template_id"]
    today_template = app.intent_library.find_by_id(first_template_id)
    selected = session["selectable_items"][0]

    assert first["view"]["type"] == "ListCard"
    assert session["last_turn"]["plan_source"] == "planner"
    assert today_template is not None
    assert today_template.intent_label == "today"
    assert app.intent_planner.snapshot()["planner_calls"] == 1

    second = app.interaction_backend.process_message("今天最紧急的是什么", session)

    assert second["view"]["type"] == "ListCard"
    assert session["last_turn"]["plan_source"] == "cache"
    assert session["last_turn"]["template_id"] == first_template_id
    assert app.intent_planner.snapshot()["cache_hits"] == 1
    assert app.intent_planner.snapshot()["planner_calls"] == 1

    correction = app.interaction_backend.process_message("不对，不是这个", session)

    assert correction["status"] == "ok"
    assert session["flywheel_feedback_events"][-1]["signal"] == "correction"
    assert session["flywheel_review_queue"][-1]["template_id"] == first_template_id
    assert today_template.correction_count == 1
    assert today_template.success_rate == pytest.approx(0.95)
    assert all("不对" not in example for example in today_template.example_inputs)

    app.interaction_backend.process_message("今天最紧急的是什么", session)
    history = app.interaction_backend.process_message("这个来源是什么", session)

    assert history["view"]["type"] == "HistoryCard"
    assert history["view"]["data"]["deadline_id"] == selected["deadline_id"]
    assert history["view"]["data"]["source_url"]
    assert today_template.missing_info_count == 1
    assert today_template.missing_info_inputs == ["这个来源是什么"]

    confirm = app.interaction_backend.process_message("完成第一条", session)

    assert confirm["view"]["type"] == "ConfirmCard"
    assert confirm["view"]["data"]["consequence"]
    assert session["pending_action_plan"]["op_class"] == "write"
    assert app.engine.get_deadline(session["tenant_id"], selected["deadline_id"]).status.value == "pending"

    done = app.interaction_backend.process_message("确认", session)

    assert done["view"]["type"] == "ListCard"
    assert "pending_action_plan" not in session
    assert session["last_turn"]["plan_source"] == "confirmed_action"
    assert app.engine.get_deadline(session["tenant_id"], selected["deadline_id"]).status.value == "completed"
