from __future__ import annotations

import json

import pytest

from duedatehq.app import create_app
from duedatehq.core.nlu_service import ClaudeNLUService
from duedatehq.core.plan_validator import PlanValidationError


class FakeClaudeNLUService(ClaudeNLUService):
    def __init__(self, *args, model_text: str, **kwargs):
        super().__init__(*args, api_key="test-key", **kwargs)
        self.model_text = model_text

    def _call_model(self, system_prompt: str, user_input: str) -> str:
        assert "Supported commands" in system_prompt
        assert user_input
        return self.model_text


class RepairingFakeClaudeNLUService(FakeClaudeNLUService):
    def _repair_model_output(self, raw_text: str) -> str:
        assert raw_text == self.model_text
        return json.dumps({"intent_label": "help", "op_class": "read", "plan": []})


def test_claude_nlu_service_validates_and_returns_plan(tmp_path):
    app = create_app(str(tmp_path / "nlu.sqlite3"))
    tenant = app.engine.create_tenant("Tenant A")
    session = {"tenant_id": tenant.tenant_id, "today": "2026-04-25", "session_id": "s1"}
    model_text = json.dumps(
        {
            "intent_label": "today",
            "op_class": "read",
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "today",
                    "cli_command": "today",
                    "args": {"tenant_id": tenant.tenant_id, "limit": 5, "enrich": True},
                }
            ],
        }
    )
    service = FakeClaudeNLUService(app.engine, model_text=model_text)

    plan = service.plan("今天先做什么", session)

    assert plan["intent_label"] == "today"
    assert plan["plan"][0]["cli_group"] == "today"


def test_claude_nlu_service_rejects_unsupported_model_command(tmp_path):
    app = create_app(str(tmp_path / "nlu.sqlite3"))
    tenant = app.engine.create_tenant("Tenant A")
    session = {"tenant_id": tenant.tenant_id, "today": "2026-04-25", "session_id": "s1"}
    model_text = json.dumps(
        {
            "intent_label": "unsafe",
            "op_class": "write",
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "email",
                    "cli_command": "send",
                    "args": {"tenant_id": tenant.tenant_id},
                }
            ],
        }
    )
    service = FakeClaudeNLUService(app.engine, model_text=model_text)

    with pytest.raises(PlanValidationError, match="unsupported command"):
        service.plan("发邮件", session)


def test_claude_nlu_service_can_extract_json_from_wrapped_text(tmp_path):
    app = create_app(str(tmp_path / "nlu.sqlite3"))
    service = FakeClaudeNLUService(app.engine, model_text="unused")

    parsed = service._extract_json_object('Here is JSON: {"special":"reference_unresolvable","message":"x"}')

    assert parsed["special"] == "reference_unresolvable"


def test_claude_nlu_service_normalizes_empty_help_plan(tmp_path):
    app = create_app(str(tmp_path / "nlu.sqlite3"))
    tenant = app.engine.create_tenant("Tenant A")
    session = {"tenant_id": tenant.tenant_id, "today": "2026-04-25", "session_id": "s1"}
    service = FakeClaudeNLUService(
        app.engine,
        model_text=json.dumps({"intent_label": "help", "op_class": "read", "plan": []}),
    )

    plan = service.plan("help", session)

    assert plan["special"] == "reference_unresolvable"
    assert plan["intent_label"] == "help"


def test_claude_nlu_service_repairs_malformed_json_once(tmp_path):
    app = create_app(str(tmp_path / "nlu.sqlite3"))
    tenant = app.engine.create_tenant("Tenant A")
    session = {"tenant_id": tenant.tenant_id, "today": "2026-04-25", "session_id": "s1"}
    service = RepairingFakeClaudeNLUService(app.engine, model_text='{"intent_label":"help"')

    plan = service.plan("怎么用", session)

    assert plan["intent_label"] == "help"
