from __future__ import annotations

import pytest

from duedatehq.core.plan_validator import PlanValidationError, PlanValidator


def test_plan_validator_accepts_supported_read_plan():
    plan = {
        "intent_label": "today",
        "op_class": "read",
        "plan": [
            {
                "step_id": "s1",
                "type": "cli_call",
                "cli_group": "today",
                "cli_command": "today",
                "args": {"tenant_id": "tenant-1", "limit": 5, "enrich": True},
            }
        ],
    }

    assert PlanValidator().validate(plan) is plan


def test_plan_validator_rejects_unknown_command():
    plan = {
        "intent_label": "bad",
        "op_class": "read",
        "plan": [
            {
                "step_id": "s1",
                "type": "cli_call",
                "cli_group": "email",
                "cli_command": "send",
                "args": {"tenant_id": "tenant-1"},
            }
        ],
    }

    with pytest.raises(PlanValidationError, match="unsupported command"):
        PlanValidator().validate(plan)


def test_plan_validator_rejects_write_command_as_read():
    plan = {
        "intent_label": "deadline_action_complete",
        "op_class": "read",
        "plan": [
            {
                "step_id": "s1",
                "type": "cli_call",
                "cli_group": "deadline",
                "cli_command": "action",
                "args": {"tenant_id": "tenant-1", "deadline_id": "deadline-1", "action": "complete"},
            }
        ],
    }

    with pytest.raises(PlanValidationError, match="op_class=write"):
        PlanValidator().validate(plan)


def test_plan_validator_rejects_write_op_without_write_command():
    plan = {
        "intent_label": "today",
        "op_class": "write",
        "plan": [
            {
                "step_id": "s1",
                "type": "cli_call",
                "cli_group": "today",
                "cli_command": "today",
                "args": {"tenant_id": "tenant-1"},
            }
        ],
    }

    with pytest.raises(PlanValidationError, match="requires at least one write command"):
        PlanValidator().validate(plan)


def test_plan_validator_accepts_guidance_plan():
    plan = {
        "special": "reference_unresolvable",
        "intent_label": "defer",
        "message": "好的，先不处理。",
        "options": ["查看今天的待处理事项"],
    }

    assert PlanValidator().validate(plan) is plan
