from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
import os
from typing import Any, Protocol

try:  # Anthropic is optional for local tests.
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - exercised only without the optional dependency
    Anthropic = None  # type: ignore[assignment]

from .models import BlockerStatus, DeadlineStatus, TaskStatus
from .nlu_service import resolve_claude_model
from .secretary_envelope import parse_secretary_envelope
from .workspace_registry import workspace_registry_prompt


ALLOWED_DATA_REQUESTS = {
    "current_view",
    "visible_deadlines",
    "all_clients",
    "all_deadlines",
    "client_deadlines",
    "client_workspace",
    "deadline_available_actions",
    "blockers",
    "tasks",
    "rules",
    "rule_review_queue",
    "notices",
}

ALLOWED_ROUTES = {
    "answer_current_view",
    "render_strategy_surface",
    "prepare_action",
    "ask_clarifying_question",
}

ALLOWED_RENDER_POLICIES = {
    "keep_current_view",
    "no_view_needed",
    "render_new_view",
    "update_current_view",
}


@dataclass(slots=True)
class AgentKernelDecision:
    route: str
    need_type: str
    render_policy: str
    data_requests: list[str]
    answer_mode: str
    view_goal: str | None = None
    answer: str | None = None
    selected_refs: list[str] | None = None
    suggested_actions: list[dict[str, str]] | None = None
    next_step: str | None = None
    surface_kind: str | None = None
    requires_confirmation: bool = False
    confidence: float = 0.0
    reason: str | None = None
    secretary_envelope: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentKernelDecision":
        envelope = parse_secretary_envelope(payload)
        if envelope:
            if envelope.action.type == "none":
                return cls(
                    route="ask_clarifying_question",
                    need_type="chat_only",
                    render_policy="no_view_needed",
                    data_requests=[],
                    answer_mode="answer_only",
                    answer=envelope.reply,
                    confidence=1.0,
                    reason="secretary envelope requested chat-only response",
                    secretary_envelope=envelope.to_dict(),
                )
            template = envelope.action.template or (envelope.action.workspace.template if envelope.action.workspace else "generated_workspace")
            return cls(
                route="render_strategy_surface",
                need_type=template,
                render_policy="render_new_view",
                data_requests=_data_requests_for_secretary_template(template),
                answer_mode="answer_and_render",
                view_goal=_view_goal_from_secretary_envelope(envelope.to_dict()),
                answer=envelope.reply,
                confidence=1.0,
                reason="secretary envelope requested render action",
                secretary_envelope=envelope.to_dict(),
            )

        data_requests = [
            str(item)
            for item in payload.get("data_requests", [])
            if str(item) in ALLOWED_DATA_REQUESTS
        ]
        selected_refs = payload.get("selected_refs")
        suggested_actions = []
        for item in payload.get("suggested_actions", []) or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            intent = str(item.get("intent") or label).strip()
            style = str(item.get("style") or "secondary").strip()
            if label and intent:
                suggested_actions.append(
                    {
                        "label": label[:48],
                        "intent": intent[:160],
                        "style": style if style in {"primary", "secondary"} else "secondary",
                    }
                )
        return cls(
            route=str(payload.get("route") or "ask_clarifying_question"),
            need_type=str(payload.get("need_type") or "chat_only"),
            render_policy=str(payload.get("render_policy") or "no_view_needed"),
            data_requests=data_requests,
            answer_mode=str(payload.get("answer_mode") or "answer_only"),
            view_goal=str(payload["view_goal"]) if payload.get("view_goal") else None,
            answer=str(payload["answer"]) if payload.get("answer") else None,
            selected_refs=[str(item) for item in selected_refs] if isinstance(selected_refs, list) else [],
            suggested_actions=suggested_actions[:3],
            next_step=str(payload["next_step"]) if payload.get("next_step") else None,
            surface_kind=str(payload["surface_kind"]) if payload.get("surface_kind") else None,
            requires_confirmation=bool(payload.get("requires_confirmation")),
            confidence=float(payload.get("confidence") or 0.0),
            reason=str(payload["reason"]) if payload.get("reason") else None,
        )

    def is_allowed(self) -> bool:
        if self.route not in ALLOWED_ROUTES:
            return False
        if self.render_policy not in ALLOWED_RENDER_POLICIES:
            return False
        if any(item not in ALLOWED_DATA_REQUESTS for item in self.data_requests):
            return False
        return True


def _data_requests_for_secretary_template(template: str) -> list[str]:
    lowered = template.casefold()
    if lowered in {"client_summary", "client_workspace", "open_workspace"} or "client" in lowered:
        return ["all_clients", "client_deadlines", "client_workspace"]
    if lowered in {"today", "today_queue", "workload_plan"}:
        return ["all_clients", "all_deadlines"]
    if "deadline" in lowered:
        return ["all_clients", "all_deadlines"]
    if "workload" in lowered or "plan" in lowered:
        return ["all_clients", "all_deadlines"]
    return ["current_view"]


def _view_goal_from_secretary_envelope(envelope: dict[str, Any]) -> str:
    action = envelope.get("action") if isinstance(envelope.get("action"), dict) else {}
    workspace = action.get("workspace") if isinstance(action.get("workspace"), dict) else {}
    fields = workspace.get("fields") if isinstance(workspace.get("fields"), dict) else {}
    entity = fields.get("entity") if isinstance(fields.get("entity"), dict) else {}
    action_field = fields.get("action") if isinstance(fields.get("action"), dict) else {}
    pieces = [str(action_field.get("value") or "").strip(), str(entity.get("value") or "").strip()]
    goal = " ".join(piece for piece in pieces if piece)
    return goal or str(action.get("template") or workspace.get("template") or "按需材料")


class AgentKernel(Protocol):
    def decide(self, user_input: str, session: dict[str, Any]) -> AgentKernelDecision | None:
        ...


class ClaudeAgentKernel:
    """Agent-native first hop for on-demand rendering.

    It lets the model infer the user's current need, but the output is still a
    constrained decision. Backend code decides which data can be read, which
    actions are allowed, and when confirmation is required.
    """

    def __init__(
        self,
        engine: Any | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_tool_rounds: int = 4,
    ) -> None:
        self.engine = engine
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or os.getenv("claude_api_key")
        self.auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN")
        self.base_url = os.getenv("ANTHROPIC_BASE_URL")
        self.model = resolve_claude_model(model or os.getenv("CLAUDE_AGENT_MODEL") or os.getenv("CLAUDE_POLICY_MODEL") or os.getenv("CLAUDE_NLU_MODEL"))
        self.client = (
            Anthropic(api_key=self.api_key, auth_token=self.auth_token, base_url=self.base_url)
            if Anthropic is not None and (self.api_key or self.auth_token)
            else None
        )
        self.max_tool_rounds = max_tool_rounds

    def decide(self, user_input: str, session: dict[str, Any]) -> AgentKernelDecision | None:
        if not self.client:
            session["last_agent_error"] = "agent client 未初始化：缺少 ANTHROPIC_API_KEY、CLAUDE_API_KEY 或 ANTHROPIC_AUTH_TOKEN。"
            return None

        try:
            raw = self._call_model(self._build_system_prompt(session), user_input, session)
        except Exception as exc:  # noqa: BLE001 - surface agent availability clearly to the caller.
            session["last_agent_error"] = f"{type(exc).__name__}: {exc}"
            return None
        try:
            payload = self._extract_json_object(raw)
        except json.JSONDecodeError as exc:
            session["last_agent_error"] = f"agent 返回的内容不是可解析 JSON：{exc}"
            return None
        decision = AgentKernelDecision.from_dict(payload)
        if not decision.is_allowed() or decision.confidence < 0.65:
            session["last_agent_error"] = "agent 返回的决策未通过 schema 或置信度校验。"
            return None
        session.pop("last_agent_error", None)
        return decision

    def _call_model(self, system_prompt: str, user_input: str, session: dict[str, Any]) -> str:
        messages = self._conversation_messages(user_input, session)
        for _ in range(self.max_tool_rounds + 1):
            response = self.client.messages.create(  # type: ignore[union-attr]
                model=self.model,
                max_tokens=1400,
                temperature=0,
                system=system_prompt,
                tools=self._tool_schemas(),
                messages=messages,
            )
            content_blocks = list(getattr(response, "content", []) or [])
            tool_uses = [block for block in content_blocks if getattr(block, "type", None) == "tool_use"]
            if not tool_uses:
                return "".join(getattr(block, "text", "") for block in content_blocks if getattr(block, "type", None) == "text")

            messages.append({"role": "assistant", "content": [self._block_to_dict(block) for block in content_blocks]})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": getattr(tool_use, "id", ""),
                            "content": json.dumps(
                                self._run_tool(getattr(tool_use, "name", ""), getattr(tool_use, "input", {}) or {}, session),
                                ensure_ascii=False,
                                default=str,
                            ),
                        }
                        for tool_use in tool_uses
                    ],
                }
            )
        return '{"route":"ask_clarifying_question","need_type":"agent_tool_loop_exhausted","render_policy":"no_view_needed","data_requests":[],"answer_mode":"answer_only","answer":"agent 这轮没有完成研判。","confidence":0}'

    def _conversation_messages(self, user_input: str, session: dict[str, Any]) -> list[dict[str, Any]]:
        """Send the real conversation to Claude, not just the latest utterance.

        Short confirmations like "好" are only meaningful when the previous
        assistant question is present as a model message.
        """
        raw_history = session.get("history_window") if isinstance(session.get("history_window"), list) else []
        messages: list[dict[str, str]] = []
        for item in raw_history[-20:]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            actor = str(item.get("actor") or "").casefold()
            role = "assistant" if actor in {"assistant", "system"} else "user"
            messages.append({"role": role, "content": text})

        if not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != user_input:
            messages.append({"role": "user", "content": user_input})
        if messages and messages[0]["role"] == "assistant":
            messages.insert(0, {"role": "user", "content": "Continue this DueDateHQ conversation. Use the prior assistant question as context."})

        merged: list[dict[str, str]] = []
        for message in messages:
            if merged and merged[-1]["role"] == message["role"]:
                merged[-1]["content"] = f"{merged[-1]['content']}\n\n{message['content']}"
            else:
                merged.append(message)
        return merged

    def _build_system_prompt(self, session: dict[str, Any]) -> str:
        context = {
            "current_view": self._summarize_view(session.get("current_view")),
            "current_workspace": session.get("current_workspace"),
            "previous_workspace": session.get("previous_workspace"),
            "workspace_registry": workspace_registry_prompt(),
            "breadcrumb": session.get("breadcrumb", []),
            "visual_context": session.get("visual_context"),
            "seen_visual_contexts": session.get("seen_visual_contexts", [])[-6:],
            "selectable_items": session.get("selectable_items", [])[:10],
            "allowed_data_requests": sorted(ALLOWED_DATA_REQUESTS),
            "allowed_routes": sorted(ALLOWED_ROUTES),
            "allowed_render_policies": sorted(ALLOWED_RENDER_POLICIES),
            "current_actions": session.get("current_actions", [])[:5],
            "state_summary": session.get("state_summary"),
            "recent_operations": session.get("operation_log", [])[-8:],
            "recent_history": session.get("history_window", [])[-8:],
        }
        return f"""
You are DueDateHQ for Sarah Johnson, an independent CPA in Texas who manages about 60 clients.

Sarah opens this product during real work. The left side is her work surface: today's queue,
client pages, deadline rows, status tags, reminders, and audit/source details. The right side
is a short conversation with you. Your job is to help her move work forward without sounding
like a generic assistant.

Core product behavior:
- Sarah says what she wants. You decide the smallest useful reply and the smallest useful UI update.
- Every answer should be bounded: draft one email, check one rule, record one operation, push one reminder,
  or answer one status question.
- Think like a controlled operator, not a commentator. Every turn should resolve to one operation class:
  navigate, read, draft, record, mutate, monitor, or refresh.
- A mutate operation is not complete until the backend has executed it and the affected workspace has been
  refreshed. Never merely say that a record was completed if the operation was not actually run.
- After any record or mutate operation, plan the next step from the refreshed state: same client remaining work,
  today's more urgent work, waiting dependency, or all clear.
- If you do something that changes work state, the result must be reflected in the work surface through
  an allowed render/action path. If a write is required, prepare it or request confirmation; never pretend
  a write happened unless the backend/action path supports it.
- Do not over-explain the system, your reasoning, templates, tools, or backend.
- Do not say "I am organizing this request", "next workspace is ready", "I will process this question",
  or similar mechanical status text.

Voice:
- Speak like a competent operations assistant for a CPA, not like a chatbot.
- Default to short, plain sentences. Usually 1-3 sentences.
- Use concrete client names, tax type, jurisdiction, due date, and status when available.
- If Sarah writes in English, answer in English. If she writes in Chinese, answer in Chinese.
- When drafting client-facing text, make the draft itself client-ready and concise.

Examples of the desired behavior:
- Opening context: "早上好。Aurora 的 federal income 5 月 15 日到期，最紧急。先处理这个？"
- User: "好。" Reply: "好，打开 Aurora。" Render/update the Aurora client workspace.
- If Aurora is open or selected, next useful reply should be concrete, e.g.
  "Aurora 缺 Q1 文件，要帮你起草催文件邮件吗？"
- User: "帮我起草催文件邮件。" Reply:
  "草稿好了：

  Hi, we're working on your federal income return, due May 15. We still need your Q1 financial records. Could you send these over by end of week?

  发出去后告我一声。"
- User: "发了。" Reply: "记下了。" Prepare/record the status update if an allowed action exists.
- User: "标记完成。" If current_actions contains a matching complete action, let the backend confirmation/write
  path handle it. Do not answer with a summary-only render.
- User: "加州今年 PTE 截止日有没有变化？" Reply: "没有，还是 5 月 30 日。有新公告我会更新你。"
- User: "今天还有什么没处理完的？" Reply:
  "Aurora 等客户回文件。Northwind PTE 还剩两条，下周处理来得及。其他都好。"

Follow-up rule:
- Short confirmations such as "好", "yes", "ok", "do that", "就这个", or "先处理这个" usually accept the
  previous assistant suggestion in recent_history. Resolve them from recent_history and current visible work
  before asking for clarification.
- If the previous assistant suggestion named Aurora / federal income / May 15, "好" means open or continue that
  Aurora work item, not "generate a generic work surface".

The product principle is: conversation never stops. Rendering is a gesture in the conversation,
like putting a file on the desk, not a replacement for replying.

Closed-loop principle:
Every operation must complete five steps: understand -> execute or confirm -> sync left/right state ->
plan next step -> present result plus next action. If you cannot execute or confirm a write, say what is
missing and do not claim the state changed.

Use native tool use plus a ReAct loop:
1. Decide the operational result Sarah needs.
2. Decide whether showing material is more information-dense than describing it.
3. Call tools when real data is needed before showing material.
4. If the user's intent or entity is missing, reply with a clarification and do not render.
5. If you render, naturally announce it in the reply only if it helps, e.g. "打开 Aurora。"

Infer what the user needs right now from:
- the user message
- current visible page
- current workspace, previous workspace, and breadcrumb
- recent operations in this session
- recently seen pages
- selectable items
- allowed data/action space

Return the Secretary Envelope schema below. Return ONLY JSON. No markdown.

Secretary Envelope schema:
{{
  "reply": "natural assistant reply; always present",
    "action": {{
      "type": "render | none",
      "announce": "verb phrase used in reply, e.g. 拉出来 | 拿出来 | 整理出来",
      "template": "today | deadline_view | client_summary | client_workspace | tax_change_radar | generated_workspace",
      "summary": "one judgment sentence for the display header",
      "highlight": ["ids mentioned in reply, e.g. deadline_001 or client_id"],
      "workspace": null | {{
      "template": "same as template",
      "fields": {{
        "entity": {{"value": "Acme Holdings LLC", "source": "user_input"}},
        "action": {{"value": "查看截止日期", "source": "user_input"}},
        "data": {{"value": null, "source": "pending"}}
      }}
    }}
  }}
}}

Field source rules:
- Every workspace field must include source.
- Allowed source values are exactly: user_input, tool_result, pending.
- source="inferred" is forbidden.
- Do not render material for an entity the user did not mention or that tools did not return.
- Data fields must come from tool_result. Use pending only before tool calls; after tool calls, replace pending with tool_result when possible.

Action rules:
- If the user input has no clear action verb, action.type="none" and reply asks what to handle.
- If the action is clear but the entity/object is missing, action.type="none" and reply asks for that entity.
- If action and entity are clear, action.type="render" only when material is more useful than text.
- To switch the left work surface to one client, use template="client_summary" or "client_workspace".
- To switch to today's queue, use template="today".
- Use generated_workspace only when no registered work surface can represent the result.
- Broad portfolio questions such as "最近有啥值得注意的", "what needs attention", "what should I look at", or "any risks" are clear enough: render a portfolio/triage surface using available deadlines, rules, notices, clients, and blockers.
- Never render instead of clarifying.
- Never render without a natural reply.
- If reply names a specific client/deadline as the key point, put the matching id in action.highlight and use the same judgment in action.summary.

Do not return the legacy route/render_policy schema. It is accepted only for old compatibility tests, not for this
product chat path.

AVAILABLE_VIEWS:
- ListCard: multiple deadlines or clients in a list.
- ClientCard: one client and its current deadlines.
- ConfirmCard: a write action that needs confirmation.
- HistoryCard: source/audit/history for one item.
- GuidanceCard: one missing bit of context or a short unblocker.
- TaxChangeRadarCard: policy, rule, notice, tax-news, or tax-change monitoring surface that shows data boundaries, rule signals, and affected client deadlines.
- RenderSpecSurface: last-resort synthesized surface for a genuinely missing product view. Do not use it for
  "好", opening a client, today's queue, draft generation, recording operations, deadline actions, or rule checks.

Context:
{json.dumps(context, ensure_ascii=False, indent=2, default=str)}
""".strip()

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_current_view",
                "description": "Read the currently rendered right-side work surface and compact visual context.",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "list_visible_deadlines",
                "description": "Read deadlines visible on the current surface, if any.",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "list_all_clients",
                "description": "List all clients for the current tenant.",
                "input_schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_all_deadlines",
                "description": "List tenant deadlines, optionally limited to a date window or status.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "within_days": {"type": "integer", "minimum": 0, "maximum": 365},
                        "status": {"type": "string", "enum": ["pending", "completed", "snoozed", "waived", "overridden"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_client_deadlines",
                "description": "List deadlines for the selected client, a client id, or a client name.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "client_id": {"type": "string"},
                        "client_name": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "completed", "snoozed", "waived", "overridden"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "open_workspace",
                "description": "Resolve and prepare a registered work surface such as TodayQueue or ClientWorkspace. Use this before deciding to open a client workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "workspace": {"type": "string", "enum": ["today", "client_workspace"]},
                        "client_id": {"type": "string"},
                        "client_name": {"type": "string"},
                    },
                    "required": ["workspace"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "deadline_available_actions",
                "description": "List allowed actions for a deadline before proposing complete/snooze/waive/override.",
                "input_schema": {
                    "type": "object",
                    "properties": {"deadline_id": {"type": "string"}},
                    "required": ["deadline_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "generate_draft",
                "description": "Generate a bounded client-facing draft for the selected or named client/deadline. This does not send anything.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "client_id": {"type": "string"},
                        "client_name": {"type": "string"},
                        "deadline_id": {"type": "string"},
                        "draft_type": {"type": "string", "enum": ["missing_documents_email"]},
                    },
                    "required": ["draft_type"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "record_operation",
                "description": "Prepare a record-operation result for the conversation. Use for notes like client email sent; persistent writes still require a backend-supported action.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "client_id": {"type": "string"},
                        "client_name": {"type": "string"},
                        "operation": {"type": "string"},
                        "deadline_id": {"type": "string"},
                    },
                    "required": ["operation"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_blockers",
                "description": "List blockers, optionally for a selected or named client.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "client_id": {"type": "string"},
                        "client_name": {"type": "string"},
                        "status": {"type": "string", "enum": ["open", "resolved", "dismissed"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_tasks",
            "description": "List operational tasks, optionally for a selected or named client.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "client_id": {"type": "string"},
                        "client_name": {"type": "string"},
                        "status": {"type": "string", "enum": ["open", "in_progress", "blocked", "done", "dismissed"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_rules",
                "description": "List internal tax rules and rule versions. Use this for policy updates, tax changes, and tax-news-like questions.",
                "input_schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_rule_review_queue",
                "description": "List low-confidence or pending rule review items.",
                "input_schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_notices",
                "description": "List imported or recorded notices for the tenant.",
                "input_schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                    "additionalProperties": False,
                },
            },
        ]

    def _run_tool(self, name: str, tool_input: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        tenant_id = session.get("tenant_id")
        try:
            if name == "get_current_view":
                return {
                    "current_view": self._summarize_view(session.get("current_view")),
                    "current_workspace": session.get("current_workspace"),
                    "previous_workspace": session.get("previous_workspace"),
                    "breadcrumb": session.get("breadcrumb", []),
                    "visual_context": session.get("visual_context"),
                    "seen_visual_contexts": session.get("seen_visual_contexts", [])[-6:],
                    "selectable_items": session.get("selectable_items", [])[:20],
                    "recent_operations": session.get("operation_log", [])[-8:],
                }
            if name == "list_visible_deadlines":
                return {"deadlines": self._visible_deadlines(session)}
            if not self.engine or not tenant_id:
                return {"error": "engine_or_tenant_missing"}
            if name == "list_all_clients":
                clients = self.engine.list_clients(tenant_id)[: int(tool_input.get("limit") or 100)]
                return {"clients": [self._serialize_client(client) for client in clients]}
            if name == "list_all_deadlines":
                status = self._deadline_status(tool_input.get("status"))
                deadlines = self.engine.list_deadlines(
                    tenant_id,
                    within_days=tool_input.get("within_days"),
                    status=status,
                    limit=int(tool_input.get("limit") or 100),
                )
                return {"deadlines": self._serialize_deadlines(tenant_id, deadlines)}
            if name == "list_client_deadlines":
                client_id = self._resolve_client_id(tenant_id, tool_input, session)
                if not client_id:
                    return {"error": "client_not_resolved", "known_clients": self._known_client_names(tenant_id)}
                deadlines = self.engine.list_deadlines(
                    tenant_id,
                    client_id,
                    status=self._deadline_status(tool_input.get("status")),
                    limit=int(tool_input.get("limit") or 100),
                )
                return {"client_id": client_id, "deadlines": self._serialize_deadlines(tenant_id, deadlines)}
            if name == "open_workspace":
                workspace = str(tool_input.get("workspace") or "")
                if workspace == "today":
                    deadlines = self.engine.today_enriched(tenant_id, 5)
                    return {
                        "workspace": "today",
                        "template": "today",
                        "deadlines": self._json_safe(deadlines),
                    }
                if workspace == "client_workspace":
                    client_id = self._resolve_client_id(tenant_id, tool_input, session)
                    if not client_id:
                        return {"error": "client_not_resolved", "known_clients": self._known_client_names(tenant_id)}
                    bundle = self.engine.get_client_bundle(tenant_id, client_id)
                    return {
                        "workspace": "client_workspace",
                        "template": "client_summary",
                        "client_id": client_id,
                        "client": self._serialize_record(bundle["client"]),
                        "deadlines": self._serialize_deadlines(tenant_id, list(bundle.get("deadlines", []))),
                        "tasks": [self._serialize_record(item) for item in list(bundle.get("tasks", []))],
                        "blockers": [self._serialize_record(item) for item in list(bundle.get("blockers", []))],
                    }
            if name == "deadline_available_actions":
                deadline_id = str(tool_input.get("deadline_id") or "")
                if not deadline_id:
                    return {"error": "deadline_id_required"}
                return self.engine.available_deadline_actions(tenant_id, deadline_id)
            if name == "generate_draft":
                return self._generate_draft_tool_result(tenant_id, tool_input, session)
            if name == "record_operation":
                client_id = self._resolve_client_id(tenant_id, tool_input, session)
                return {
                    "operation": str(tool_input.get("operation") or ""),
                    "client_id": client_id,
                    "client_name": tool_input.get("client_name"),
                    "deadline_id": tool_input.get("deadline_id"),
                    "status": "prepared",
                    "write_boundary": "conversation operation only; persistent writes require backend action support",
                }
            if name == "list_blockers":
                client_id = self._resolve_client_id(tenant_id, tool_input, session)
                blockers = self.engine.list_blockers(
                    tenant_id,
                    client_id,
                    status=self._blocker_status(tool_input.get("status")),
                    limit=int(tool_input.get("limit") or 100),
                )
                return {"blockers": [self._serialize_record(blocker) for blocker in blockers]}
            if name == "list_tasks":
                client_id = self._resolve_client_id(tenant_id, tool_input, session)
                tasks = self.engine.list_tasks(
                    tenant_id,
                    client_id,
                    status=self._task_status(tool_input.get("status")),
                    limit=int(tool_input.get("limit") or 100),
                )
                return {"tasks": [self._serialize_record(task) for task in tasks]}
            if name == "list_rules":
                limit = int(tool_input.get("limit") or 100)
                return {"rules": [self._serialize_record(rule) for rule in self.engine.list_rules()[:limit]]}
            if name == "list_rule_review_queue":
                limit = int(tool_input.get("limit") or 100)
                return {"review_queue": [self._serialize_record(item) for item in self.engine.list_rule_review_queue()[:limit]]}
            if name == "list_notices":
                limit = int(tool_input.get("limit") or 100)
                return {"notices": [self._serialize_record(item) for item in self.engine.list_notices(tenant_id, limit=limit)]}
        except (KeyError, ValueError, TypeError) as exc:
            return {"error": type(exc).__name__, "message": str(exc)}
        return {"error": "unknown_tool", "tool": name}

    def _generate_draft_tool_result(self, tenant_id: str, tool_input: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        client_id = self._resolve_client_id(tenant_id, tool_input, session)
        if not client_id:
            return {"error": "client_not_resolved", "known_clients": self._known_client_names(tenant_id)}
        client = self.engine.get_client(tenant_id, client_id)
        deadlines = self.engine.list_deadlines(tenant_id, client_id=client_id, status=DeadlineStatus.PENDING, limit=20)
        deadline_id = str(tool_input.get("deadline_id") or "")
        selected = next((item for item in deadlines if item.deadline_id == deadline_id), deadlines[0] if deadlines else None)
        if not selected:
            return {"error": "deadline_not_resolved", "client_id": client_id, "client_name": client.name}
        missing_item = "Q1 financial records"
        draft = (
            f"Hi,\n\n"
            f"We're working on your {selected.tax_type} return, due {selected.due_date.isoformat()}. "
            f"We still need your {missing_item}. Could you send these over by end of week?\n\n"
            f"Thank you,\nSarah"
        )
        return {
            "client_id": client_id,
            "client_name": client.name,
            "deadline_id": selected.deadline_id,
            "tax_type": selected.tax_type,
            "jurisdiction": selected.jurisdiction,
            "due_date": selected.due_date.isoformat(),
            "draft": draft,
        }

    def _block_to_dict(self, block: Any) -> dict[str, Any]:
        if isinstance(block, dict):
            return block
        block_type = getattr(block, "type", None)
        if block_type == "text":
            return {"type": "text", "text": getattr(block, "text", "")}
        if block_type == "tool_use":
            return {
                "type": "tool_use",
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}) or {},
            }
        data = {"type": block_type}
        if hasattr(block, "model_dump"):
            data.update({key: value for key, value in block.model_dump().items() if value is not None})
        return data

    def _visible_deadlines(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        view = session.get("current_view")
        if not isinstance(view, dict):
            return []
        data = view.get("data") if isinstance(view.get("data"), dict) else {}
        rows = data.get("items") or data.get("deadlines") or []
        return [dict(item) for item in rows if isinstance(item, dict)]

    def _serialize_deadlines(self, tenant_id: str, deadlines: list[Any]) -> list[dict[str, Any]]:
        client_names = {
            client.client_id: client.name
            for client in self.engine.list_clients(tenant_id)
        } if self.engine else {}
        serialized = []
        for deadline in deadlines:
            data = self._serialize_record(deadline)
            data["client_name"] = client_names.get(data.get("client_id"), data.get("client_id"))
            serialized.append(data)
        return serialized

    def _serialize_client(self, client: Any) -> dict[str, Any]:
        data = self._serialize_record(client)
        return {
            "client_id": data.get("client_id"),
            "name": data.get("name"),
            "entity_type": data.get("entity_type"),
            "registered_states": data.get("registered_states", []),
            "tax_year": data.get("tax_year"),
            "responsible_cpa": data.get("responsible_cpa"),
            "is_active": data.get("is_active"),
        }

    def _serialize_record(self, record: Any) -> dict[str, Any]:
        if is_dataclass(record):
            raw = asdict(record)
        elif isinstance(record, dict):
            raw = dict(record)
        else:
            raw = dict(getattr(record, "__dict__", {}))
        return {key: self._json_safe(value) for key, value in raw.items()}

    def _json_safe(self, value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        return value

    def _resolve_client_id(self, tenant_id: str, tool_input: dict[str, Any], session: dict[str, Any]) -> str | None:
        if tool_input.get("client_id"):
            return str(tool_input["client_id"])
        name = str(tool_input.get("client_name") or "").casefold().strip()
        if name and self.engine:
            for client in self.engine.list_clients(tenant_id):
                if name in client.name.casefold() or client.name.casefold() in name:
                    return client.client_id
        current = session.get("current_view")
        if isinstance(current, dict):
            data = current.get("data") if isinstance(current.get("data"), dict) else {}
            if data.get("client_id"):
                return str(data["client_id"])
        selectable = session.get("selectable_items") or []
        for item in selectable:
            if isinstance(item, dict) and item.get("client_id"):
                return str(item["client_id"])
        return None

    def _known_client_names(self, tenant_id: str) -> list[str]:
        if not self.engine:
            return []
        return [client.name for client in self.engine.list_clients(tenant_id)[:20]]

    def _deadline_status(self, status: Any) -> DeadlineStatus | None:
        return DeadlineStatus(str(status)) if status else None

    def _blocker_status(self, status: Any) -> BlockerStatus | None:
        return BlockerStatus(str(status)) if status else None

    def _task_status(self, status: Any) -> TaskStatus | None:
        return TaskStatus(str(status)) if status else None

    def _summarize_view(self, view: Any) -> dict[str, Any] | None:
        if not isinstance(view, dict):
            return None
        data = view.get("data") if isinstance(view.get("data"), dict) else {}
        summary: dict[str, Any] = {"type": view.get("type")}
        for key in ("title", "headline", "description", "message", "client_name", "total", "status_label"):
            if key in data:
                summary[key] = data[key]
        if isinstance(data.get("items"), list):
            summary["items"] = [
                {
                    "ref": f"item_{index}",
                    "client_name": item.get("client_name"),
                    "tax_type": item.get("tax_type"),
                    "jurisdiction": item.get("jurisdiction"),
                    "due_date": item.get("due_date"),
                    "status": item.get("status"),
                    "days_remaining": item.get("days_remaining"),
                }
                for index, item in enumerate(data["items"][:10], start=1)
                if isinstance(item, dict)
            ]
        if isinstance(data.get("deadlines"), list):
            summary["deadlines"] = [
                {
                    "ref": f"item_{index}",
                    "tax_type": item.get("tax_type"),
                    "jurisdiction": item.get("jurisdiction"),
                    "due_date": item.get("due_date"),
                    "status": item.get("status"),
                    "days_remaining": item.get("days_remaining"),
                }
                for index, item in enumerate(data["deadlines"][:10], start=1)
                if isinstance(item, dict)
            ]
        return summary

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("{"):
            parsed = json.loads(stripped)
        else:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start == -1 or end == -1 or end < start:
                raise json.JSONDecodeError("no json object", text, 0)
            parsed = json.loads(stripped[start : end + 1])
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("json must be object", text, 0)
        return parsed
