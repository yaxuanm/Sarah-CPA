from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.agent_kernel import AgentKernelDecision


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "interaction.sqlite3"))


def _seed_interaction_data(app):
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
    session = {"tenant_id": tenant.tenant_id, "today": today.isoformat(), "session_id": "session-1"}
    return tenant, client, deadline, session


def test_interaction_backend_processes_read_plan(app):
    tenant, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_plan(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "today",
                    "cli_command": "today",
                    "args": {"tenant_id": tenant.tenant_id, "limit": 5, "enrich": True},
                }
            ],
            "intent_label": "today",
            "op_class": "read",
        },
        session,
    )

    assert response["view"]["type"] == "ListCard"
    assert response["view"]["data"]["items"]


def test_interaction_backend_returns_confirm_card_for_write_plan(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_plan(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "action",
                    "args": {"tenant_id": tenant.tenant_id, "deadline_id": deadline.deadline_id, "action": "complete"},
                }
            ],
            "intent_label": "deadline_action_complete",
            "op_class": "write",
        },
        session,
    )

    assert response["view"]["type"] == "ConfirmCard"
    assert response["view"]["data"]["options"][0]["plan"]["op_class"] == "write"


def test_interaction_backend_processes_confirmed_action(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_action(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "action",
                    "args": {"tenant_id": tenant.tenant_id, "deadline_id": deadline.deadline_id, "action": "complete"},
                }
            ],
            "intent_label": "deadline_action_complete",
            "op_class": "write",
        },
        session,
    )

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ListCard"
    assert response["session_id"] == "session-1"


def test_interaction_backend_direct_confirm_command_executes_pending_action(app):
    tenant, _, deadline, session = _seed_interaction_data(app)
    confirm = app.interaction_backend.process_direct_action(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "action",
                    "args": {"tenant_id": tenant.tenant_id, "deadline_id": deadline.deadline_id, "action": "complete"},
                }
            ],
            "intent_label": "deadline_action_complete",
            "op_class": "write",
        },
        session,
    )

    assert confirm["view"]["type"] == "ConfirmCard"
    assert session["pending_action_plan"]["op_class"] == "write"

    done = app.interaction_backend.process_direct_command("confirm_pending", session)

    assert done["status"] == "ok"
    assert done["view"]["type"] == "ListCard"
    assert "pending_action_plan" not in session
    assert app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value == "completed"
    assert session["last_turn"]["plan_source"] == "direct_action_confirm"


def test_interaction_backend_turns_entity_not_found_into_guidance(app):
    tenant, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_plan(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "resolve_entity",
                    "entity_name": "Missing LLC",
                    "entity_type": "client",
                    "args": {"tenant_id": tenant.tenant_id},
                    "match_field": "name",
                    "bind_as": "resolved_client",
                }
            ],
            "intent_label": "client_deadline_list",
            "op_class": "read",
        },
        session,
    )

    assert response["view"]["type"] == "GuidanceCard"


def test_interaction_backend_message_renders_today_and_remembers_selectable_items(app):
    _, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_message("今天先做什么", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ListCard"
    assert session["selectable_items"][0]["deadline_id"]
    assert session["current_view"]["type"] == "ListCard"
    assert session["current_workspace"]["type"] == "TodayQueue"
    assert session["breadcrumb"] == ["TodayQueue"]
    assert session["operation_log"][0]["intent_label"] == "today"


def test_interaction_backend_long_tail_need_renders_constrained_surface(app):
    _, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_message("帮我写一封很强硬但礼貌的客户催资料邮件", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "RenderSpecSurface"
    spec = response["view"]["data"]["render_spec"]
    assert spec["surface"] == "work_card"
    assert spec["version"] == "0.1"
    assert any(block["type"] == "choice_set" for block in spec["blocks"])
    assert response["view"]["type"] == session["current_view"]["type"]


def test_interaction_backend_draft_request_uses_current_task_context(app):
    _, _, _, session = _seed_interaction_data(app)
    app.interaction_backend.process_message("先看 Acme", session)

    response = app.interaction_backend.process_message("prepare a draft", session)

    assert response["view"]["type"] == "RenderSpecSurface"
    spec = response["view"]["data"]["render_spec"]
    assert "Acme" in spec["title"]
    assert any(block["type"] == "action_draft" for block in spec["blocks"])
    choice_block = next(block for block in spec["blocks"] if block["type"] == "choice_set")
    choices = {choice["label"]: choice for choice in choice_block["choices"]}
    assert choices["记录为已发送"]["action"]["type"] == "direct_execute"
    assert choices["记录为已发送"]["action"]["expected_view"] == "ConfirmCard"
    assert choices["记录为已发送"]["action"]["plan"]["op_class"] == "write"
    assert choices["查看依据"]["action"]["expected_view"] == "HistoryCard"
    assert choices["回到今日清单"]["action"]["expected_view"] == "ListCard"
    assert "发送" in response["message"] or "草稿" in response["message"]


def test_interaction_backend_prepare_request_no_longer_hits_known_route_when_agent_hands_off(app):
    _, _, _, session = _seed_interaction_data(app)
    app.interaction_backend.process_message("先看 Acme", session)
    app.interaction_backend.agent_kernel = FakeAgentKernel(
        AgentKernelDecision(
            route="pass_to_planner",
            need_type="workflow_or_navigation",
            render_policy="pass_to_planner",
            data_requests=["current_view"],
            answer_mode="pass_to_planner",
            confidence=0.95,
        )
    )

    response = app.interaction_backend.process_message("prepare request", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "RenderSpecSurface"
    spec = response["view"]["data"]["render_spec"]
    assert "Acme" in spec["title"]
    assert any(block["type"] == "action_draft" for block in spec["blocks"])
    assert session["last_turn"]["intent_label"] == "ad_hoc_render_spec"
    assert session["last_turn"].get("plan_source") != "known_route"


def test_interaction_backend_message_focuses_client_by_name(app):
    _, _, _, session = _seed_interaction_data(app)

    response = app.interaction_backend.process_message("先看 Acme", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_name"] == "Acme LLC"


def test_interaction_backend_opens_numbered_visible_item(app):
    tenant, _, _, session = _seed_interaction_data(app)
    today = datetime.now(timezone.utc).date()
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Second LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )

    app.interaction_backend.process_message("今天先做什么", session)
    expected_client_id = session["selectable_items"][1]["client_id"]
    response = app.interaction_backend.process_message("打开第 2 条", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_id"] == expected_client_id


def test_interaction_backend_explains_all_visible_list_items(app):
    tenant, _, _, session = _seed_interaction_data(app)
    today = datetime.now(timezone.utc).date()
    for name in ["Second LLC", "Third LLC"]:
        app.engine.register_client(
            tenant_id=tenant.tenant_id,
            name=name,
            entity_type="s-corp",
            registered_states=["CA"],
            tax_year=today.year,
        )

    listed = app.interaction_backend.process_message("今天先做什么", session)
    response = app.interaction_backend.process_message("这几件事分别是什么", session)

    visible_names = [item["client_name"] for item in listed["view"]["data"]["items"]]
    assert response["status"] == "ok"
    assert response["view"]["type"] == "ListCard"
    assert response["view"] == listed["view"]
    for name in visible_names:
        assert name in response["message"]
    assert "打开第 N 条" in response["message"]


def test_interaction_backend_answers_context_advice_without_replacing_page(app):
    _, _, _, session = _seed_interaction_data(app)
    focused = app.interaction_backend.process_message("先看 Acme", session)

    response = app.interaction_backend.process_message("急着处理么？", session)

    assert focused["view"]["type"] == "ClientCard"
    assert response["status"] == "ok"
    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_name"] == "Acme LLC"
    assert response["message"]
    assert "Acme LLC" in response["message"]
    assert session["last_turn"]["intent_label"] == "answer_advice"
    assert session["last_turn"]["plan_source"] == "agent_kernel"
    assert session["last_agent_kernel"]["render_policy"] == "keep_current_view"


def test_interaction_backend_renders_agent_portfolio_surface_without_selected_item(app):
    tenant, _, _, session = _seed_interaction_data(app)
    today = datetime.now(timezone.utc).date()
    for name in ["Beta LLC", "Cedar LLC"]:
        app.engine.register_client(
            tenant_id=tenant.tenant_id,
            name=name,
            entity_type="s-corp",
            registered_states=["CA"],
            tax_year=today.year,
        )
    app.interaction_backend.agent_kernel = FakeAgentKernel(
        AgentKernelDecision(
            route="render_strategy_surface",
            need_type="client_portfolio_status",
            render_policy="render_new_view",
            data_requests=["all_clients", "all_deadlines"],
            answer_mode="answer_and_render",
            view_goal="看所有客户的整体状态",
            answer="我按所有客户和待处理 deadline 整理了一个工作面。",
            suggested_actions=[{"label": "查看风险最高客户", "intent": "打开风险最高客户", "style": "primary"}],
            confidence=0.9,
        )
    )

    response = app.interaction_backend.process_message("我所有的客户的情况如何", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "RenderSpecSurface"
    assert response["view"]["data"]["render_spec"]["title"] == "看所有客户的整体状态"
    assert "客户" in response["message"]
    assert session["last_turn"]["intent_label"] == "client_portfolio_status"
    assert session["last_turn"]["plan_source"] == "agent_kernel"
    choice_block = next(block for block in response["view"]["data"]["render_spec"]["blocks"] if block["type"] == "choice_set")
    assert choice_block["choices"] == [{"label": "查看风险最高客户", "intent": "打开风险最高客户", "style": "primary"}]


def test_interaction_backend_renders_agent_priority_surface(app):
    tenant, _, _, session = _seed_interaction_data(app)
    today = datetime.now(timezone.utc).date()
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Later LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    app.interaction_backend.process_message("今天先做什么", session)
    app.interaction_backend.agent_kernel = FakeAgentKernel(
        AgentKernelDecision(
            route="render_strategy_surface",
            need_type="deadline_urgency_comparison",
            render_policy="render_new_view",
            data_requests=["visible_deadlines", "all_deadlines"],
            answer_mode="answer_and_render",
            view_goal="比较当前事项的紧急程度",
            answer="我比较了当前可见事项，右侧保留排序依据。",
            confidence=0.9,
        )
    )

    response = app.interaction_backend.process_message("哪个客户最不紧急", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "RenderSpecSurface"
    assert response["view"]["data"]["render_spec"]["title"] == "比较当前事项的紧急程度"
    assert "排序依据" in response["message"]
    assert session["last_turn"]["intent_label"] == "deadline_urgency_comparison"
    assert session["last_turn"]["plan_source"] == "agent_kernel"
    assert not session.get("flywheel_feedback_events")


def test_interaction_backend_agent_strategy_surface_hides_internal_fallback_terms(app):
    tenant, _, _, session = _seed_interaction_data(app)
    today = datetime.now(timezone.utc).date()
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Later LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    app.interaction_backend.process_message("今天先做什么", session)
    app.interaction_backend.agent_kernel = FakeAgentKernel(
        AgentKernelDecision(
            route="render_strategy_surface",
            need_type="least_urgent_client",
            render_policy="render_new_view",
            data_requests=["current_view", "blockers", "tasks"],
            answer_mode="answer_and_render",
            view_goal="帮我比较一下哪个客户最不紧急",
            answer="综合截止日、待处理数量和是否有阻塞，Later LLC 可以最后处理。",
            suggested_actions=[{"label": "打开 Later LLC", "intent": "打开 Later LLC", "style": "primary"}],
            confidence=0.9,
        )
    )

    response = app.interaction_backend.process_message("帮我比较一下哪个客户最不紧急", session)

    spec = response["view"]["data"]["render_spec"]
    rendered_text = str(spec)
    assert response["view"]["type"] == "RenderSpecSurface"
    assert "本轮只读取" not in rendered_text
    assert "current_view" not in rendered_text
    assert "当前范围" not in rendered_text
    assert "0 个待处理" not in rendered_text
    assert "结论" in rendered_text
    assert "Later LLC" in rendered_text
    assert response["view"]["selectable_items"]


@pytest.mark.parametrize(
    "user_input",
    [
        "有什么特别值得关注的税务新闻吗？",
        "最近有什么政策更新吗",
        "最近有什么新规会影响客户吗",
    ],
)
def test_interaction_backend_policy_change_uses_agent_surface_not_generic_fallback(app, user_input):
    _, _, _, session = _seed_interaction_data(app)
    app.interaction_backend.process_message("今天先做什么", session)
    app.interaction_backend.agent_kernel = FakeAgentKernel(
        AgentKernelDecision(
            route="render_strategy_surface",
            need_type="tax_change_monitoring",
            render_policy="render_new_view",
            data_requests=["rules", "rule_review_queue", "notices", "all_clients", "all_deadlines"],
            answer_mode="answer_and_render",
            view_goal="查看最近政策、规则或 notice 是否会影响当前客户",
            surface_kind="TaxChangeRadar",
            answer="我会按政策变化雷达查看哪些变化可能影响客户。",
            confidence=0.9,
        )
    )

    response = app.interaction_backend.process_message(user_input, session)

    data = response["view"]["data"]
    rendered_text = str(data)
    assert response["view"]["type"] == "TaxChangeRadarCard"
    assert data["title"] == "本月税务变化雷达"
    assert "实时外部税务新闻源" in data["data_boundary_notice"]
    assert data["rule_signals"]
    assert data["impacted_deadlines"]
    assert "政策变化雷达" in response["message"]
    assert "current_view" not in rendered_text
    assert response["actions"][0]["action"]["type"] == "direct_execute"
    assert session["last_turn"]["intent_label"] == "tax_change_monitoring"
    assert session["last_turn"]["plan_source"] == "agent_kernel"


class FakeAgentKernel:
    def __init__(self, decision: AgentKernelDecision):
        self.decision = decision

    def decide(self, user_input, session):
        return self.decision


def test_interaction_backend_known_visible_item_route_handles_agent_handoff(app):
    _, _, _, session = _seed_interaction_data(app)
    app.interaction_backend.process_message("今天先做什么", session)
    expected_client_id = session["selectable_items"][0]["client_id"]
    app.interaction_backend.agent_kernel = FakeAgentKernel(
        AgentKernelDecision(
            route="pass_to_planner",
            need_type="workflow_or_navigation",
            render_policy="pass_to_planner",
            data_requests=["current_view", "client_deadlines"],
            answer_mode="pass_to_planner",
            confidence=0.95,
        )
    )

    response = app.interaction_backend.process_message("打开第 1 条", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "ClientCard"
    assert response["view"]["data"]["client_id"] == expected_client_id
    assert session["previous_workspace"]["type"] == "TodayQueue"
    assert session["current_workspace"]["type"] == "ClientWorkspace"
    assert session["breadcrumb"][-2:] == ["TodayQueue", "ClientWorkspace"]
    assert session["operation_log"][-1]["workspace_ref"] == session["current_workspace"]["key"]
    assert session["last_turn"]["intent_label"] == "client_deadline_list"
    assert session["last_turn"]["plan_source"] == "known_route"


def test_interaction_backend_renders_generic_agent_strategy_surface(app):
    _, _, _, session = _seed_interaction_data(app)
    app.interaction_backend.process_message("先看 Acme", session)
    app.interaction_backend.agent_kernel = FakeAgentKernel(
        AgentKernelDecision(
            route="render_strategy_surface",
            need_type="client_work_summary",
            render_policy="render_new_view",
            data_requests=["current_view", "client_deadlines"],
            answer_mode="answer_and_render",
            view_goal="整理这个客户当前这些事情的情况",
            suggested_actions=[{"label": "继续追问", "intent": "这些事情还有什么风险", "style": "primary"}],
            confidence=0.9,
            reason="generic synthesis",
        )
    )

    response = app.interaction_backend.process_message("这些事情情况如何", session)

    assert response["status"] == "ok"
    assert response["view"]["type"] == "RenderSpecSurface"
    spec = response["view"]["data"]["render_spec"]
    assert spec["title"]
    assert spec["surface"] == "work_card"
    assert any(block["type"] == "source_list" for block in spec["blocks"])
    choice_block = next(block for block in spec["blocks"] if block["type"] == "choice_set")
    assert choice_block["choices"][0]["label"] == "继续追问"
    assert response["view"]["selectable_items"]
    assert session["last_turn"]["intent_label"] == "client_work_summary"
    assert session["last_turn"]["plan_source"] == "agent_kernel"


def test_interaction_backend_message_requires_confirmation_before_write(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    app.interaction_backend.process_message("今天先做什么", session)
    confirm = app.interaction_backend.process_message("完成第一条", session)

    assert confirm["view"]["type"] == "ConfirmCard"
    assert session["pending_action_plan"]["op_class"] == "write"
    assert app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value == "pending"

    done = app.interaction_backend.process_message("确认", session)

    assert done["status"] == "ok"
    assert "pending_action_plan" not in session
    assert app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value == "completed"


def test_interaction_backend_resolves_cross_turn_reference_from_today_to_current_item(app):
    _, _, _, session = _seed_interaction_data(app)

    today = app.interaction_backend.process_message("今天先做什么", session)
    focused = app.interaction_backend.process_message("看第一条", session)
    selectable_after_focus = list(session["selectable_items"])
    history = app.interaction_backend.process_message("刚才那个为什么变了", session)
    confirm = app.interaction_backend.process_message("完成这个", session)

    assert today["view"]["type"] == "ListCard"
    assert focused["view"]["type"] == "ClientCard"
    assert history["view"]["type"] == "HistoryCard"
    assert session["selectable_items"][0]["deadline_id"] == selectable_after_focus[0]["deadline_id"]
    assert session["selectable_items"][0]["client_id"] == selectable_after_focus[0]["client_id"]
    assert confirm["view"]["type"] == "ConfirmCard"
    assert session["pending_action_plan"]["op_class"] == "write"


def test_interaction_backend_blocks_due_date_edit_from_audit_workspace(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    app.interaction_backend.process_message("先看 Acme", session)
    history = app.interaction_backend.process_message("这个来源是什么", session)
    response = app.interaction_backend.process_message("把这个截止日期改一下", session)

    assert history["view"]["type"] == "HistoryCard"
    assert response["view"]["type"] == "GuidanceCard"
    assert response["view"]["data"]["title"] == "先回到可操作的工作区"
    assert "不能直接修改截止日" in response["message"]
    assert response["actions"][0]["label"] == "回到客户工作区"
    assert response["actions"][0]["action"]["type"] == "direct_execute"
    assert response["actions"][0]["action"]["expected_view"] == "ClientCard"
    assert app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value == "pending"
    assert session["last_turn"]["plan_source"] == "workspace_guard"


def test_interaction_backend_can_cancel_and_resume_cross_turn_write(app):
    tenant, _, deadline, session = _seed_interaction_data(app)

    app.interaction_backend.process_message("先看 Acme", session)
    app.interaction_backend.process_message("这个来源是什么", session)
    first_confirm = app.interaction_backend.process_message("完成当前这个", session)
    cancelled = app.interaction_backend.process_message("取消", session)
    second_confirm = app.interaction_backend.process_message("完成刚才那个", session)
    before = app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value
    done = app.interaction_backend.process_message("确认", session)
    after = app.engine.get_deadline(tenant.tenant_id, deadline.deadline_id).status.value

    assert first_confirm["view"]["type"] == "ConfirmCard"
    assert cancelled["view"]["type"] == "GuidanceCard"
    assert "pending_action_plan" not in session
    assert second_confirm["view"]["type"] == "ConfirmCard"
    assert before == "pending"
    assert done["view"]["type"] == "ListCard"
    assert after == "completed"
