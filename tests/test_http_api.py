from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.core.models import NotificationChannel
from duedatehq.http_api import _instant_response_prefix, _latest_new_feedback_event, _message_chunks, _sse, _thinking_status, create_fastapi_app


def _seed_api_deadline(api):
    today = datetime.now(timezone.utc).date()
    tenant = api.state.app_state.engine.create_tenant("Tenant A")
    api.state.app_state.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=2)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://ftb.ca.gov/r1",
        confidence_score=0.99,
    )
    api.state.app_state.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    return tenant


def test_sse_helper_formats_event_payload():
    payload = _sse("intent_confirmed", {"intent_label": "today"})

    assert payload.startswith("event: intent_confirmed\n")
    assert 'data: {"intent_label": "today"}' in payload
    assert payload.endswith("\n\n")


def test_message_chunks_preserve_streamed_message():
    message = "1. **Acme** — pending\n2. **Greenway** — pending"
    chunks = _message_chunks(message, chunk_size=10)

    assert len(chunks) > 1
    assert "".join(chunks) == message


def test_message_chunks_prefer_natural_boundaries():
    message = "第一句说明。第二句补充。第三句收尾。"
    chunks = _message_chunks(message, chunk_size=8)

    assert len(chunks) > 1
    assert chunks[0].endswith("。")
    assert "".join(chunks) == message


def test_instant_response_prefix_uses_current_view_context():
    assert _instant_response_prefix("看下今天的情况", {"current_view": {"type": "ListCard"}}).startswith("好的，我帮你看看今天")
    assert _instant_response_prefix("总体情况如何", {}).startswith("好的，我来处理")
    assert _instant_response_prefix("最近有什么政策更新吗", {}).startswith("好的，我帮你查一下哪些变化")
    assert "放在一起比较" not in _instant_response_prefix("最近有什么政策更新吗", {})


def test_thinking_status_is_user_facing_not_internal_log():
    assert _thinking_status("有什么税务新闻", {}) == "正在读取规则库、notice 和近期 deadline。"
    assert _thinking_status("最近有什么政策更新吗", {}) == "正在读取规则库、notice 和近期 deadline。"
    assert "当前页面和后台数据" in _thinking_status("总体情况如何", {"current_view": {"type": "ListCard"}})
    assert "我先看" not in _thinking_status("总体情况如何", {"current_view": {"type": "ListCard"}})


def test_fastapi_app_requires_optional_dependency(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fastapi":
            raise ImportError("missing fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="duedatehq\\[api\\]"):
        create_fastapi_app()


def test_fastapi_app_allows_frontend_origin(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-cors.sqlite3"))
    client = TestClient(api)

    response = client.options(
        "/chat/stream",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

    response = client.options(
        "/review/impact/tenant-a",
        headers={
            "Origin": "http://127.0.0.1:5182",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5182"


def test_review_impact_endpoint_returns_backend_interpretation(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-review-impact.sqlite3"))
    tenant = api.state.app_state.engine.create_tenant("Tenant Review API")
    api.state.app_state.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Sierra Wholesale Inc.",
        entity_type="c-corp",
        registered_states=["TX", "CA"],
        tax_year=2026,
    )
    api.state.app_state.engine.fetch_from_source(
        state="TX",
        raw_text="Texas Comptroller updated economic nexus guidance; threshold changed but no due date was stated.",
        source_url="https://comptroller.texas.gov/about/media-center/news/economic-nexus.html",
        fetched_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        actor="test",
    )
    client = TestClient(api)

    response = client.get(f"/review/impact/{tenant.tenant_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rule_reviews"][0]["source"]["display_name"] == "Texas Comptroller News Releases"
    assert payload["rule_reviews"][0]["affected_clients"][0]["client_name"] == "Sierra Wholesale Inc."


def test_import_preview_endpoint_returns_ai_assist_payload(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-import-preview.sqlite3"))
    client = TestClient(api)

    response = client.post(
        "/import/preview",
        json={
            "source_name": "portfolio.csv",
            "csv_text": "Account,Return Kind,Markets,Home\nNorthwind Services LLC,LLC,CA,CA\n",
            "mapping_overrides": {"Account": "client_name", "Return Kind": "entity_type", "Markets": "operating_states", "Home": "home_jurisdiction"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready_to_generate"] is True
    assert payload["ai_assist"]["normalized_clients"][0]["client_name"] == "Northwind Services LLC"


def test_policy_interpret_endpoint_matches_affected_clients(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-policy-interpret.sqlite3"))
    tenant = api.state.app_state.engine.create_tenant("Tenant Policy Interpret")
    api.state.app_state.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Aurora Tech Labs",
        entity_type="c-corp",
        registered_states=["CA"],
        tax_year=2026,
    )
    client = TestClient(api)

    response = client.post(
        f"/review/interpret/{tenant.tenant_id}",
        json={
            "state": "CA",
            "source_url": "https://www.ftb.ca.gov/about-ftb/newsroom/pte-election-update.html",
            "raw_text": "California FTB says the PTE election deadline moves to May 30, 2026.",
            "fetched_at": "2026-04-25T12:00:00+00:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["display_name"] == "California Franchise Tax Board Newsroom"
    assert payload["affected_clients"][0]["client_name"] == "Aurora Tech Labs"


def test_settings_endpoint_updates_notification_route(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-settings.sqlite3"))
    tenant = api.state.app_state.engine.create_tenant("Tenant Settings API")
    route = api.state.app_state.engine.configure_notification_route(
        tenant.tenant_id,
        NotificationChannel.EMAIL,
        "owner@example.com",
        actor="test",
    )
    client = TestClient(api)

    settings = client.get(f"/settings/{tenant.tenant_id}")
    assert settings.status_code == 200
    assert settings.json()["notification_summary"]["enabled_channels"] == 1

    response = client.patch(
        f"/settings/{tenant.tenant_id}/notification-routes/{route.route_id}",
        json={"enabled": False, "destination": "ops@example.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"]["enabled"] is False
    assert payload["route"]["destination"] == "ops@example.com"
    assert payload["settings"]["notification_summary"]["enabled_channels"] == 0


def test_email_draft_endpoint_uses_deadline_context(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-email-draft.sqlite3"))
    tenant = api.state.app_state.engine.create_tenant("Tenant Email Draft API")
    api.state.app_state.engine.create_rule(
        tax_type="federal_income",
        jurisdiction="FEDERAL",
        entity_types=["s-corp"],
        deadline_date="2026-05-15",
        effective_from="2026-01-01",
        source_url="https://irs.gov/r1",
        confidence_score=0.99,
    )
    client_record = api.state.app_state.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=2026,
        primary_contact_name="Maya Chen",
        primary_contact_email="maya@example.com",
    )
    deadline = api.state.app_state.engine.list_deadlines(tenant.tenant_id, client_record.client_id)[0]
    client = TestClient(api)

    response = client.post(
        f"/clients/{tenant.tenant_id}/{client_record.client_id}/email/draft",
        json={"deadline_id": deadline.deadline_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["to"] == "maya@example.com"
    assert "Acme LLC" in payload["subject"]


def test_bootstrap_today_uses_fast_default_entry(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-bootstrap.sqlite3"))
    client = TestClient(api)

    response = client.post(
        "/bootstrap/today",
        json={"tenant_id": "tenant-a", "session": {"session_id": "bootstrap-session"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["view"]["type"] == "ListCard"
    assert payload["session"]["last_turn"]["plan_source"] == "bootstrap"
    assert payload["session"]["current_view"]["type"] == "ListCard"
    assert payload["session"]["current_workspace"]["type"] == "TodayQueue"
    assert payload["session"]["previous_workspace"] is None
    assert payload["session"]["breadcrumb"] == ["TodayQueue"]
    assert payload["session"]["operation_log"][0]["plan_source"] == "bootstrap"


def test_action_endpoint_executes_direct_read_without_agent(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-action.sqlite3"))
    tenant = _seed_api_deadline(api)
    client = TestClient(api)
    bootstrap = client.post(
        "/bootstrap/today",
        json={"tenant_id": tenant.tenant_id, "session": {"session_id": "direct-action-session"}},
    ).json()
    action = bootstrap["response"]["view"]["selectable_items"][0]["action"]

    response = client.post(
        "/action",
        json={"tenant_id": tenant.tenant_id, "session": bootstrap["session"], "action": action},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["view"]["type"] == "ClientCard"
    assert payload["session"]["last_turn"]["plan_source"] == "direct_action"
    assert payload["session"]["previous_workspace"]["type"] == "TodayQueue"
    assert payload["session"]["current_workspace"]["type"] == "ClientWorkspace"
    assert payload["session"]["breadcrumb"][-2:] == ["TodayQueue", "ClientWorkspace"]


def test_action_endpoint_keeps_write_actions_behind_confirm_card(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-action-write.sqlite3"))
    tenant = _seed_api_deadline(api)
    client = TestClient(api)
    bootstrap = client.post(
        "/bootstrap/today",
        json={"tenant_id": tenant.tenant_id, "session": {"session_id": "direct-write-session"}},
    ).json()
    write_plan = bootstrap["response"]["actions"][0]["plan"]

    response = client.post(
        "/action",
        json={"tenant_id": tenant.tenant_id, "session": bootstrap["session"], "plan": write_plan},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["view"]["type"] == "ConfirmCard"
    assert payload["session"]["pending_action_plan"]["op_class"] == "write"
    assert payload["session"]["last_turn"]["plan_source"] == "direct_action"


def test_action_endpoint_confirms_pending_action_without_chat_route(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-action-confirm.sqlite3"))
    tenant = _seed_api_deadline(api)
    client = TestClient(api)
    bootstrap = client.post(
        "/bootstrap/today",
        json={"tenant_id": tenant.tenant_id, "session": {"session_id": "direct-confirm-session"}},
    ).json()
    write_plan = bootstrap["response"]["actions"][0]["plan"]
    confirm = client.post(
        "/action",
        json={"tenant_id": tenant.tenant_id, "session": bootstrap["session"], "plan": write_plan},
    ).json()

    response = client.post(
        "/action",
        json={
            "tenant_id": tenant.tenant_id,
            "session": confirm["session"],
            "action": {"type": "direct_execute", "command": "confirm_pending"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["view"]["type"] == "ListCard"
    assert "pending_action_plan" not in payload["session"]
    assert payload["session"]["last_turn"]["plan_source"] == "direct_action_confirm"


def test_latest_new_feedback_event_ignores_stale_events():
    session = {
        "flywheel_feedback_events": [{"signal": "missing_info", "user_input": "old"}],
    }

    assert _latest_new_feedback_event(session, 1) is None

    session["flywheel_feedback_events"].append({"signal": "correction", "user_input": "不对"})
    assert _latest_new_feedback_event(session, 1) == {"signal": "correction", "user_input": "不对"}
