from __future__ import annotations

import pytest

from duedatehq.http_api import _latest_new_feedback_event, _message_chunks, _sse, create_fastapi_app


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


def test_latest_new_feedback_event_ignores_stale_events():
    session = {
        "flywheel_feedback_events": [{"signal": "missing_info", "user_input": "old"}],
    }

    assert _latest_new_feedback_event(session, 1) is None

    session["flywheel_feedback_events"].append({"signal": "correction", "user_input": "不对"})
    assert _latest_new_feedback_event(session, 1) == {"signal": "correction", "user_input": "不对"}
