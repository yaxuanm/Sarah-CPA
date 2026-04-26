from __future__ import annotations

import json

from duedatehq.core.agent_kernel import ClaudeAgentKernel, DeterministicAgentKernel


def test_deterministic_agent_kernel_does_not_route_semantic_overview():
    kernel = DeterministicAgentKernel()

    decision = kernel.decide("我所有的客户的情况如何", {})

    assert decision is None


def test_deterministic_agent_kernel_routes_current_view_answer():
    kernel = DeterministicAgentKernel()
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

    decision = kernel.decide("这几件事分别是什么", session)

    assert decision is not None
    assert decision.route == "answer_current_view"
    assert decision.render_policy == "keep_current_view"


def test_deterministic_agent_kernel_passes_workflow_to_planner():
    kernel = DeterministicAgentKernel()

    decision = kernel.decide("打开第 2 条", {"current_view": {"type": "ListCard", "data": {"items": []}}})

    assert decision is not None
    assert decision.route == "pass_to_planner"


class FakeClaudeAgentKernel(ClaudeAgentKernel):
    def __init__(self, model_text: str):
        super().__init__(api_key="test-key")
        self.model_text = model_text

    def _call_model(self, system_prompt: str, user_input: str, session: dict) -> str:
        assert "DueDateHQ's Agent Kernel" in system_prompt
        assert user_input
        assert isinstance(session, dict)
        return self.model_text


def test_claude_agent_kernel_parses_constrained_decision():
    kernel = FakeClaudeAgentKernel(
        json.dumps(
            {
                "route": "render_strategy_surface",
                "need_type": "client_portfolio_status",
                "render_policy": "render_new_view",
                "data_requests": ["all_clients", "all_deadlines", "not_allowed"],
                "answer_mode": "answer_and_render",
                "view_goal": "show the portfolio",
                "answer": "我会先看全部客户。",
                "selected_refs": [],
                "suggested_actions": [
                    {"label": "看风险最高客户", "intent": "打开风险最高的客户", "style": "primary"},
                    {"label": "回到今日清单", "intent": "查看今天的待处理事项", "style": "secondary"},
                ],
                "next_step": "先看最紧急客户。",
                "requires_confirmation": False,
                "confidence": 0.91,
                "reason": "portfolio question",
            }
        )
    )

    decision = kernel.decide("give me a management surface", {})

    assert decision is not None
    assert decision.route == "render_strategy_surface"
    assert decision.data_requests == ["all_clients", "all_deadlines"]
    assert decision.suggested_actions == [
        {"label": "看风险最高客户", "intent": "打开风险最高的客户", "style": "primary"},
        {"label": "回到今日清单", "intent": "查看今天的待处理事项", "style": "secondary"},
    ]


def test_claude_agent_kernel_low_confidence_uses_fallback():
    kernel = FakeClaudeAgentKernel(
        json.dumps(
            {
                "route": "answer_current_view",
                "need_type": "answer_advice",
                "render_policy": "keep_current_view",
                "data_requests": ["current_view"],
                "answer_mode": "answer_only",
                "confidence": 0.2,
            }
        )
    )

    decision = kernel.decide("我所有的客户的情况如何", {})

    assert decision is None


class FakeBlock:
    def __init__(self, block_type: str, **kwargs):
        self.type = block_type
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return FakeResponse(
                [
                    FakeBlock(
                        "tool_use",
                        id="tool-1",
                        name="get_current_view",
                        input={},
                    )
                ]
            )
        assert self.calls[-1]["messages"][-1]["content"][0]["type"] == "tool_result"
        return FakeResponse(
            [
                FakeBlock(
                    "text",
                    text=json.dumps(
                        {
                            "route": "render_strategy_surface",
                            "need_type": "current_surface_summary",
                            "render_policy": "render_new_view",
                            "data_requests": ["current_view"],
                            "answer_mode": "answer_and_render",
                            "view_goal": "explain the currently visible queue",
                            "confidence": 0.9,
                        }
                    ),
                )
            ]
        )


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


def test_claude_agent_kernel_uses_native_tool_loop_before_final_decision():
    kernel = ClaudeAgentKernel(api_key="test-key")
    fake_client = FakeClient()
    kernel.client = fake_client
    session = {
        "current_view": {
            "type": "ListCard",
            "data": {
                "items": [
                    {
                        "client_name": "Acme LLC",
                        "tax_type": "federal_income",
                        "jurisdiction": "FEDERAL",
                        "due_date": "2026-04-25",
                        "status": "pending",
                    }
                ]
            },
        }
    }

    decision = kernel.decide("这些事情情况如何", session)

    assert decision is not None
    assert decision.route == "render_strategy_surface"
    assert decision.need_type == "current_surface_summary"
    assert len(fake_client.messages.calls) == 2
    assert fake_client.messages.calls[0]["tools"]
