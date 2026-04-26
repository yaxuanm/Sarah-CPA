from __future__ import annotations

import json

from duedatehq.core.agent_policy import ClaudeAgentPolicyService, DeterministicAgentPolicyService


def test_deterministic_agent_policy_keeps_current_list_for_explanation():
    service = DeterministicAgentPolicyService()
    session = {
        "current_view": {
            "type": "ListCard",
            "data": {
                "items": [
                    {"client_name": "Acme LLC", "tax_type": "sales_tax", "due_date": "2026-04-25", "status": "pending"}
                ]
            },
        }
    }

    decision = service.decide("这几件事分别是什么", session)

    assert decision is not None
    assert decision.need_type == "explain_current_view"
    assert decision.render_policy == "keep_current_view"


def test_deterministic_agent_policy_passes_navigation_to_planner():
    service = DeterministicAgentPolicyService()
    session = {
        "current_view": {
            "type": "ListCard",
            "data": {"items": []},
        }
    }

    assert service.decide("打开第 2 条", session) is None


def test_deterministic_agent_policy_routes_portfolio_overview_to_strategy_surface():
    service = DeterministicAgentPolicyService()

    decision = service.decide("我所有的客户的情况如何", {})

    assert decision is not None
    assert decision.need_type == "portfolio_overview"
    assert decision.render_policy == "render_new_view"
    assert "all_clients" in (decision.data_requests or [])


def test_deterministic_agent_policy_routes_least_urgent_to_strategy_surface():
    service = DeterministicAgentPolicyService()

    decision = service.decide("哪个客户最不紧急", {"current_view": {"type": "ListCard", "data": {"items": []}}})

    assert decision is not None
    assert decision.need_type == "deadline_priority_ranking"
    assert decision.render_policy == "render_new_view"


class FakeClaudeAgentPolicyService(ClaudeAgentPolicyService):
    def __init__(self, model_text: str):
        super().__init__(api_key="test-key")
        self.model_text = model_text

    def _call_model(self, system_prompt: str, user_input: str) -> str:
        assert "DueDateHQ's agent policy layer" in system_prompt
        assert user_input
        return self.model_text


def test_claude_agent_policy_parses_structured_decision():
    service = FakeClaudeAgentPolicyService(
        json.dumps(
            {
                "need_type": "answer_advice",
                "render_policy": "keep_current_view",
                "data_requests": ["current_view"],
                "answer_mode": "answer_only",
                "view_goal": None,
                "answer": "这五件事都在右侧列表里。",
                "selected_refs": [],
                "next_step": "可以打开第 1 条。",
                "requires_confirmation": False,
                "confidence": 0.91,
                "reason": "current view contains the list",
            }
        )
    )

    decision = service.decide("这五件事分别是什么", {"current_view": {"type": "ListCard", "data": {"items": []}}})

    assert decision is not None
    assert decision.need_type == "answer_advice"
    assert decision.render_policy == "keep_current_view"
    assert "右侧列表" in (decision.answer or "")


def test_claude_agent_policy_low_confidence_falls_through():
    service = FakeClaudeAgentPolicyService(
        json.dumps(
            {
                "need_type": "answer_advice",
                "render_policy": "keep_current_view",
                "confidence": 0.2,
            }
        )
    )

    assert service.decide("whatever", {}) is None
