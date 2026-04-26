from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.followup_feedback import classify_followup


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DUEDATEHQ_USE_FLYWHEEL_ROUTER", "1")
    monkeypatch.delenv("DUEDATEHQ_USE_CLAUDE_NLU", raising=False)
    return create_app(str(tmp_path / "followup.sqlite3"))


def _seed_feedback_data(app):
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


def test_classify_followup_signals():
    last_turn = {"intent_label": "today"}

    assert classify_followup(last_turn, "不对，不是这个").signal == "correction"
    assert classify_followup(last_turn, "这个来源是什么").signal == "missing_info"
    assert classify_followup(last_turn, "展开看看").signal == "drill_down"
    assert classify_followup(None, "不对").signal == "none"


def test_followup_correction_marks_template_for_review(app):
    session = _seed_feedback_data(app)

    app.interaction_backend.process_message("今天先做什么", session)
    previous_template_id = session["last_turn"]["template_id"]
    template = app.intent_library.find_by_id(previous_template_id)
    assert template is not None

    app.interaction_backend.process_message("不对，不是这个", session)

    assert session["flywheel_feedback_events"][0]["signal"] == "correction"
    assert session["flywheel_review_queue"][0]["template_id"] == previous_template_id
    assert template.correction_count == 1
    assert template.success_rate == pytest.approx(0.95)
    assert all("不对" not in example for example in template.example_inputs)


def test_followup_missing_info_records_missing_field_request(app):
    session = _seed_feedback_data(app)

    app.interaction_backend.process_message("今天先做什么", session)
    previous_intent = session["last_turn"]["intent_label"]
    template = next(template for template in app.intent_library.all() if template.intent_label == previous_intent)

    app.interaction_backend.process_message("这个来源是什么", session)

    assert session["flywheel_feedback_events"][0]["signal"] == "missing_info"
    assert template.missing_info_count == 1
    assert template.missing_info_inputs == ["这个来源是什么"]
