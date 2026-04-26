from __future__ import annotations

from datetime import datetime, timedelta, timezone

from duedatehq.app import create_app
from duedatehq.cli import main as cli_main
from duedatehq.core.persistent_intent_cache import SQLiteIntentLibrary


def _seed_persistent_data(app):
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


def test_sqlite_intent_library_persists_templates_and_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("DUEDATEHQ_PERSIST_FLYWHEEL", "1")
    db_path = str(tmp_path / "persistent.sqlite3")
    app = create_app(db_path)
    session = _seed_persistent_data(app)

    plan = app.intent_planner.plan("今天先做什么", session)
    template = app.intent_library.learn("今天先做什么", plan, session)
    app.intent_library.record_feedback(
        template.intent_id,
        is_correction=True,
        user_input="不对，不是这个",
        reason="explicit correction phrase",
    )
    app.intent_library.record_missing_field("today", "这个来源是什么", "question asks for missing context")

    reloaded = create_app(db_path)

    assert isinstance(reloaded.intent_library, SQLiteIntentLibrary)
    assert reloaded.intent_library.stats()["template_count"] == 1
    match = reloaded.intent_library.match("今天最紧急的是什么", session)
    assert match is not None
    assert match.template.intent_label == "today"
    assert match.template.correction_count == 1
    assert match.template.missing_info_count == 1
    assert reloaded.intent_library.feedback_events(signal="correction")[0]["user_input"] == "不对，不是这个"
    assert reloaded.intent_library.review_queue()[0]["intent_label"] == "today"


def test_flywheel_cli_reads_persistent_metrics(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DUEDATEHQ_PERSIST_FLYWHEEL", "1")
    db_path = str(tmp_path / "persistent-cli.sqlite3")
    app = create_app(db_path)
    session = _seed_persistent_data(app)
    plan = app.intent_planner.plan("今天先做什么", session)
    template = app.intent_library.learn("今天先做什么", plan, session)
    app.intent_library.record_feedback(template.intent_id, is_correction=True, user_input="wrong")

    monkeypatch.setattr("sys.argv", ["duedatehq", "--db", db_path, "flywheel", "stats"])
    assert cli_main() == 0
    stats_output = capsys.readouterr().out
    assert '"template_count": 1' in stats_output
    assert '"corrections": 1' in stats_output

    monkeypatch.setattr("sys.argv", ["duedatehq", "--db", db_path, "flywheel", "review-queue"])
    assert cli_main() == 0
    review_output = capsys.readouterr().out
    assert "today" in review_output
