from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.flywheel import LabeledFlywheelInput, run_convergence_test, run_labeled_convergence_test, run_labeled_holdout_test
from duedatehq.core.intent_samples import BASIC_FLYWHEEL_SAMPLES


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "flywheel.sqlite3"))


def _seed_flywheel_data(app):
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
    }


def test_flywheel_convergence_test_reports_second_round_hits(app):
    session = _seed_flywheel_data(app)
    inputs = [
        "今天先做什么",
        "今天最紧急的是什么",
        "show today's list",
        "先看 Acme",
        "打开 Acme LLC",
        "完成第一条",
        "mark first done",
    ]

    result = run_convergence_test(inputs, planner=app.intent_planner, session=session)

    assert result.total_inputs == len(inputs)
    assert result.second_round_hit_rate >= 0.70
    assert result.template_count <= 4
    assert not result.missed_inputs


def test_labeled_flywheel_convergence_tracks_wrong_matches(app):
    session = _seed_flywheel_data(app)
    result = run_labeled_convergence_test(BASIC_FLYWHEEL_SAMPLES, planner=app.intent_planner, session=session)

    assert result.second_round_hit_rate >= 0.90
    assert result.second_round_accuracy >= 0.90
    assert result.template_count <= 12
    assert not result.planner_mismatches
    assert not result.cache_mismatches


def test_labeled_flywheel_holdout_measures_unseen_inputs(app):
    session = _seed_flywheel_data(app)

    result = run_labeled_holdout_test(BASIC_FLYWHEEL_SAMPLES, planner=app.intent_planner, session=session)

    assert result.test_inputs > 0
    assert result.hit_rate >= 0.80
    assert result.accuracy >= 0.80
    assert result.template_count <= 12
