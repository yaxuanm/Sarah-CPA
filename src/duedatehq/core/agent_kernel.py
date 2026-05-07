from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
import os
from typing import Any, Protocol

try:  # Anthropic is optional for local deterministic tests.
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
    "pass_to_planner",
}

ALLOWED_RENDER_POLICIES = {
    "keep_current_view",
    "no_view_needed",
    "render_new_view",
    "update_current_view",
    "pass_to_planner",
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
            route=str(payload.get("route") or "pass_to_planner"),
            need_type=str(payload.get("need_type") or "pass_to_planner"),
            render_policy=str(payload.get("render_policy") or "pass_to_planner"),
            data_requests=data_requests,
            answer_mode=str(payload.get("answer_mode") or "pass_to_planner"),
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
    return goal or str(action.get("template") or workspace.get("template") or "On-demand material")


class AgentKernel(Protocol):
    def decide(self, user_input: str, session: dict[str, Any]) -> AgentKernelDecision | None:
        ...


class DeterministicAgentKernel:
    """Small local guardrail for workflow turns when Claude is unavailable.

    Semantic synthesis should come from ClaudeAgentKernel. This fallback only
    protects obvious workflow/navigation turns and simple current-page answers,
    so old keyword policies do not compete with the Agent loop.
    """

    def decide(self, user_input: str, session: dict[str, Any]) -> AgentKernelDecision | None:
        text = user_input.strip().casefold()
        if not text:
            return None
        if self._looks_like_tax_change_need(text):
            return None

        if self._looks_like_navigation_or_write(text):
            return AgentKernelDecision(
                route="pass_to_planner",
                need_type="workflow_or_navigation",
                render_policy="pass_to_planner",
                data_requests=[],
                answer_mode="pass_to_planner",
                confidence=0.95,
                reason="existing planner handles navigation and write flows",
            )

        current_view = session.get("current_view")
        if isinstance(current_view, dict) and current_view.get("type") and self._looks_like_surface_question(text):
            need_type = "explain_current_view" if current_view.get("type") == "ListCard" else "answer_advice"
            return AgentKernelDecision(
                route="answer_current_view",
                need_type=need_type,
                render_policy="keep_current_view",
                data_requests=["current_view"],
                answer_mode="answer_only",
                view_goal="answer from the current work surface without replacing it",
                confidence=0.82,
                reason="current visible surface likely contains enough context",
            )

        return None

    def _looks_like_navigation_or_write(self, text: str) -> bool:
        terms = [
            "打开",
            "切到",
            "转到",
            "回到",
            "返回",
            "标记",
            "完成",
            "确认",
            "取消",
            "起草",
            "生成",
            "发送",
            "show source",
            "back",
            "go to",
            "open ",
            "focus ",
            "mark ",
            "complete",
            "confirm",
            "cancel",
            "draft",
            "prepare",
        ]
        return any(term in text for term in terms)

    def _looks_like_surface_question(self, text: str) -> bool:
        if self._looks_like_tax_change_need(text):
            return False
        blocked_source_terms = ["来源", "变更", "变了", "谁改", "历史", "source", "history", "changed"]
        if any(term in text for term in blocked_source_terms):
            return False
        broad_queue_terms = ["今天", "today", "列表", "待处理", "todo", "queue"]
        explain_terms = ["分别", "哪些", "是什么", "解释", "说明", "说一下", "list them", "what are", "explain"]
        if any(term in text for term in broad_queue_terms) and not any(term in text for term in explain_terms):
            return False
        question_terms = [
            "?",
            "？",
            "什么",
            "哪些",
            "分别",
            "解释",
            "说明",
            "说一下",
            "怎么",
            "为什么",
            "急",
            "重要",
            "风险",
            "优先",
            "下一步",
            "怎么办",
            "what",
            "which",
            "why",
            "how",
            "urgent",
            "priority",
            "risk",
        ]
        return any(term in text for term in question_terms)

    def _looks_like_tax_change_need(self, text: str) -> bool:
        subject_terms = ["政策", "法规", "规则", "税务", "税法", "税收", "policy", "regulation", "rule", "tax", "notice"]
        change_terms = ["更新", "变化", "变更", "新闻", "新规", "最近", "关注", "update", "change", "news", "recent"]
        return any(term in text for term in subject_terms) and any(term in text for term in change_terms)


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
        self.model = resolve_claude_model(model or os.getenv("CLAUDE_AGENT_MODEL") or os.getenv("CLAUDE_POLICY_MODEL") or os.getenv("CLAUDE_NLU_MODEL"))
        self.client = Anthropic(api_key=self.api_key) if Anthropic is not None and self.api_key else None
        self.max_tool_rounds = max_tool_rounds
        self.fallback = DeterministicAgentKernel()

    def decide(self, user_input: str, session: dict[str, Any]) -> AgentKernelDecision | None:
        deterministic = self.fallback.decide(user_input, session)
        if not self.client:
            return deterministic

        try:
            raw = self._call_model(self._build_system_prompt(session), user_input, session)
        except Exception as exc:  # noqa: BLE001 - keep deterministic fallback available during demos.
            session["last_agent_error"] = f"{type(exc).__name__}: {exc}"
            return deterministic
        try:
            payload = self._extract_json_object(raw)
        except json.JSONDecodeError as exc:
            session["last_agent_error"] = f"Agent returned content that was not parseable JSON: {exc}"
            return deterministic
        decision = AgentKernelDecision.from_dict(payload)
        if not decision.is_allowed() or decision.confidence < 0.65:
            session["last_agent_error"] = "Agent decision failed schema or confidence validation."
            return deterministic
        if decision.route == "pass_to_planner":
            return deterministic or decision
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
        return '{"route":"pass_to_planner","need_type":"tool_loop_exhausted","render_policy":"pass_to_planner","data_requests":[],"answer_mode":"pass_to_planner","confidence":0}'

    def _conversation_messages(self, user_input: str, session: dict[str, Any]) -> list[dict[str, Any]]:
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
You are DueDateHQ's Agent Kernel.

Sarah opens this product during real work. The left side is her work surface: today's queue,
client pages, deadline rows, status tags, reminders, and audit/source details. The right side
is a short conversation with you. Your job is to help her move work forward without sounding
like a generic assistant.

Core product behavior:
- Sarah says what she wants. You decide the smallest useful reply and the smallest useful UI update.
- Every answer should be bounded: draft one email, check one rule, record one operation, push one reminder,
  or answer one status question.
- Think like a controlled operator. Every turn should resolve to one operation class:
  navigate, read, draft, record, mutate, monitor, or refresh.
- A mutate operation is not complete until the backend has executed it and the affected workspace has been
  refreshed. Never claim a record changed unless the backend/action path supports that change.
- After any record or mutate operation, plan the next step from the refreshed state.
- Do not over-explain the system, your reasoning, templates, tools, or backend.

Voice:
- Speak like a competent operations assistant for a CPA, not like a chatbot.
- Default to short, plain sentences. Usually 1-3 sentences.
- Use concrete client names, tax type, jurisdiction, due date, and status when available.
- Always answer in English by default, even when Sarah writes in Chinese. You may understand Chinese input, but user-visible replies, workspace summaries, labels, and drafts should be English unless Sarah explicitly asks for a Chinese translation.
- When drafting client-facing text, make the draft itself client-ready and concise.

Follow-up rule:
- Short confirmations such as "好", "yes", "ok", "do that", "就这个", or "先处理这个" usually accept the
  previous assistant suggestion in recent_history. Resolve them from recent_history and current visible work
  before asking for clarification.
- If the previous assistant suggestion named Acme / federal income / May 15, "好" means open or continue that
  Acme work item, not "generate a generic work surface".

The product principle is: conversation never stops. Rendering is a gesture in the conversation,
like putting a file on the desk, not a replacement for replying.

Use native tool use plus a ReAct loop:
1. Decide the operational result Sarah needs.
2. Decide whether showing material is more information-dense than describing it.
3. Call tools when real data is needed before showing material.
4. If the user's intent or entity is missing, reply with a clarification and do not render.
5. If you render, naturally announce it in the reply only if it helps, e.g. "Opening Acme."

Infer what the user needs right now from:
- the user message
- current visible page
- current workspace, previous workspace, and breadcrumb
- recent operations in this session
- recently seen pages
- selectable items
- allowed data/action space

Prefer the Secretary Envelope schema. Return ONLY JSON. No markdown.

Secretary Envelope schema:
{{
  "reply": "natural English assistant reply; always present",
  "action": {{
    "type": "render | none",
    "announce": "English verb phrase used in reply, e.g. Pull supporting material | Open workspace | Prepare draft",
    "template": "today | deadline_view | client_summary | client_workspace | tax_change_radar | generated_workspace",
    "summary": "one English judgment sentence for the display header",
    "highlight": ["ids mentioned in reply, e.g. deadline_001 or client_id"],
    "workspace": null | {{
      "template": "same as template",
      "fields": {{
        "entity": {{"value": "Acme Holdings LLC", "source": "user_input"}},
        "action": {{"value": "view deadlines", "source": "user_input"}},
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
- Broad portfolio questions such as "what needs attention", "what should I look at", "any risks", or equivalent Chinese input are clear enough: render a portfolio/triage surface using available deadlines, rules, notices, clients, and blockers.
- Never render instead of clarifying.
- Never render without a natural reply.

Legacy decision schema is still accepted for compatibility:
{{
  "route": "answer_current_view | render_strategy_surface | prepare_action | ask_clarifying_question | pass_to_planner",
  "need_type": "short semantic label, e.g. client_risk_review, workload_comparison, explain_current_view",
  "render_policy": "keep_current_view | no_view_needed | update_current_view | render_new_view | pass_to_planner",
  "data_requests": ["current_view | visible_deadlines | all_clients | all_deadlines | client_deadlines | blockers | tasks | rules | rule_review_queue | notices"],
  "answer_mode": "answer_only | answer_and_render | render_only | pass_to_planner",
  "view_goal": "what the right-side surface should help the user decide",
  "surface_kind": "TaxChangeRadar | ClientImpactMatrix | WeeklyExecutionList | SourceAudit | null",
  "answer": "optional concise answer if current context is already enough",
  "selected_refs": ["item_1"],
  "suggested_actions": [
    {{"label": "short button label", "intent": "natural language prompt to send if clicked", "style": "primary | secondary"}}
  ],
  "next_step": "one concrete next step, or null",
  "requires_confirmation": false,
  "confidence": 0.0,
  "reason": "short internal reason"
}}

Rules:
- Prefer answer_current_view only when the current page already contains enough information and a new surface would not improve decision-making.
- If the user asks for a synthesis, comparison, prioritization, overview, status, explanation of multiple visible items, or "what should I do", prefer render_strategy_surface and request the minimum allowed data.
- If the user asks about policy updates, tax news, rule changes, notices, regulations, or recent changes that may affect clients, use render_strategy_surface with surface_kind="TaxChangeRadar" and request rules, rule_review_queue, notices, all_clients, and all_deadlines.
- For unknown but useful UI needs, choose render_strategy_surface with a clear view_goal.
- For normal natural-language workflow requests, reason about the user's real need first. Do not pass to the planner just because the text contains words like open, prepare, draft, mark, send, or complete.
- Use pass_to_planner only when the message is clearly a deterministic UI/navigation command already covered by visible action contracts, or when you cannot improve on the existing deterministic planner.
- Never execute writes. If a write may be needed, choose prepare_action and requires_confirmation=true.
- Do not invent facts. If facts are needed, call tools before final JSON.
- If a user asks a normal advisory question, answer conversationally and still choose whether the current view should stay or a better surface should be rendered.
- Suggested actions are optional. Include only actions that directly follow from your tool results and the user's stated need. Do not emit generic or canned actions just to fill space.

AVAILABLE_VIEWS:
- ListCard: multiple deadlines or clients in a list.
- ClientCard: one client and its current deadlines.
- ConfirmCard: a write action that needs confirmation.
- HistoryCard: source/audit/history for one item.
- GuidanceCard: one missing bit of context or a short unblocker.
- TaxChangeRadarCard: policy, rule, notice, tax-news, or tax-change monitoring surface that shows data boundaries, rule signals, and affected client deadlines.
- RenderSpecSurface: synthesized or ad-hoc work surface for comparisons, portfolio status, prioritization, risk, explanation, or a view not yet hard-coded.

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
