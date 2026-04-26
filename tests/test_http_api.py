from __future__ import annotations

import pytest

from duedatehq.http_api import _sse, create_fastapi_app


def test_sse_helper_formats_event_payload():
    payload = _sse("intent_confirmed", {"intent_label": "today"})

    assert payload.startswith("event: intent_confirmed\n")
    assert 'data: {"intent_label": "today"}' in payload
    assert payload.endswith("\n\n")


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
