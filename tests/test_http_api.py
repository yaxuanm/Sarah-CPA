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


def test_sources_sync_endpoint_routes_supported_states_to_review_queue(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-source-sync.sqlite3"))
    client = TestClient(api)

    response = client.post("/sources/sync", json={"states": ["CA", "TX", "NY"]})

    assert response.status_code == 200
    payload = response.json()
    assert [item["fetch_run"]["source_key"] for item in payload["results"]] == ["state_ca", "state_tx", "state_ny"]
    assert all(item["fetch_run"]["status"] == "review_queued" for item in payload["results"])


def test_sources_status_endpoint_reports_latest_run(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-source-status.sqlite3"))
    client = TestClient(api)
    client.post("/sources/sync", json={"states": ["CA"]})

    response = client.get("/sources/status")

    assert response.status_code == 200
    ca_source = next(item for item in response.json()["sources"] if item["source_key"] == "state_ca")
    assert ca_source["sync_supported"] is True
    assert ca_source["latest_fetch_run"]["status"] == "review_queued"


def test_dashboard_payload_endpoint_returns_board_data(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-dashboard.sqlite3"))
    tenant = _seed_api_deadline(api)
    client = TestClient(api)

    response = client.post("/dashboard/payload", json={"tenant_id": tenant.tenant_id, "limit": 3})

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["client_count"] == 1
    assert payload["today"][0]["client_name"] == "Acme LLC"


def test_notification_preview_and_send_pending_endpoints(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    api = create_fastapi_app(str(tmp_path / "http-notifications.sqlite3"))
    tenant = _seed_api_deadline(api)
    api.state.app_state.engine.configure_notification_route(
        tenant.tenant_id,
        NotificationChannel.EMAIL,
        "sarah@example.com",
    )
    client = TestClient(api)

    preview = client.post("/notifications/preview", json={"tenant_id": tenant.tenant_id, "within_days": 30})

    assert preview.status_code == 200
    assert len(preview.json()["routes"]) == 1
    assert preview.json()["reminders"]

    send = client.post(
        "/notifications/send-pending",
        json={"tenant_id": tenant.tenant_id, "trigger_due": True, "at": "2100-01-01T00:00:00+00:00"},
    )

    assert send.status_code == 200
    assert send.json()["sent"] >= 1
    assert {item["status"] for item in send.json()["deliveries"]} == {"sent"}


def test_latest_new_feedback_event_ignores_stale_events():
    session = {
        "flywheel_feedback_events": [{"signal": "missing_info", "user_input": "old"}],
    }

    assert _latest_new_feedback_event(session, 1) is None

    session["flywheel_feedback_events"].append({"signal": "correction", "user_input": "不对"})
    assert _latest_new_feedback_event(session, 1) == {"signal": "correction", "user_input": "不对"}
