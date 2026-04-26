from __future__ import annotations

from dataclasses import dataclass
import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol

from .nlu_service import ANTHROPIC_API_URL, resolve_claude_model


@dataclass(slots=True)
class AgentPolicyDecision:
    need_type: str
    render_policy: str
    answer: str | None = None
    selected_refs: list[str] | None = None
    data_requests: list[str] | None = None
    answer_mode: str | None = None
    view_goal: str | None = None
    next_step: str | None = None
    requires_confirmation: bool = False
    confidence: float = 0.0
    reason: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentPolicyDecision":
        selected_refs = payload.get("selected_refs")
        data_requests = payload.get("data_requests")
        return cls(
            need_type=str(payload.get("need_type") or "pass_to_planner"),
            render_policy=str(payload.get("render_policy") or "pass_to_planner"),
            answer=str(payload["answer"]) if payload.get("answer") else None,
            selected_refs=[str(item) for item in selected_refs] if isinstance(selected_refs, list) else [],
            data_requests=[str(item) for item in data_requests] if isinstance(data_requests, list) else [],
            answer_mode=str(payload["answer_mode"]) if payload.get("answer_mode") else None,
            view_goal=str(payload["view_goal"]) if payload.get("view_goal") else None,
            next_step=str(payload["next_step"]) if payload.get("next_step") else None,
            requires_confirmation=bool(payload.get("requires_confirmation")),
            confidence=float(payload.get("confidence") or 0.0),
            reason=str(payload["reason"]) if payload.get("reason") else None,
        )


class AgentPolicy(Protocol):
    def decide(self, user_input: str, session: dict[str, Any]) -> AgentPolicyDecision | None:
        ...


class DeterministicAgentPolicyService:
    """Conservative policy layer used when the LLM policy is disabled.

    It only intercepts cases where the current rendered surface clearly already
    contains the information the user is asking about. Everything else continues
    through the normal planner/executor path.
    """

    def decide(self, user_input: str, session: dict[str, Any]) -> AgentPolicyDecision | None:
        text = user_input.strip().casefold()
        if not text or self._looks_like_command(text):
            return None
        current_view = session.get("current_view")

        if self._looks_like_portfolio_overview(text):
            return AgentPolicyDecision(
                need_type="portfolio_overview",
                render_policy="render_new_view",
                data_requests=["all_clients", "all_deadlines"],
                answer_mode="answer_and_render",
                view_goal="show client portfolio status and risk",
                confidence=0.88,
                reason="user asks about all clients, not one selected task",
            )

        if self._looks_like_least_urgent_question(text):
            return AgentPolicyDecision(
                need_type="deadline_priority_ranking",
                render_policy="render_new_view",
                data_requests=["visible_deadlines", "all_deadlines"],
                answer_mode="answer_and_render",
                view_goal="rank deadlines by urgency and identify the least urgent item",
                confidence=0.86,
                reason="user asks for comparative priority across items",
            )

        if not isinstance(current_view, dict) or not current_view.get("type"):
            return None

        view_type = current_view.get("type")
        if view_type == "ListCard" and self._looks_like_current_surface_question(text):
            return AgentPolicyDecision(
                need_type="explain_current_view",
                render_policy="keep_current_view",
                confidence=0.9,
                reason="question can be answered from the visible list",
            )
        if view_type in {"ClientCard", "HistoryCard", "RenderSpecSurface"} and self._looks_like_current_surface_question(text):
            return AgentPolicyDecision(
                need_type="answer_advice",
                render_policy="keep_current_view",
                confidence=0.82,
                reason="question can be answered from the current work surface",
            )
        return None

    def _looks_like_command(self, text: str) -> bool:
        command_terms = [
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
        return any(term in text for term in command_terms)

    def _looks_like_current_surface_question(self, text: str) -> bool:
        source_terms = ["来源", "变更", "变了", "为什么变", "谁改", "谁更新", "历史", "source", "history", "changed"]
        if any(term in text for term in source_terms):
            return False
        broad_list_terms = ["今天", "today", "列表", "待处理", "todo", "queue"]
        current_page_question_terms = [
            "分别",
            "哪些",
            "是什么",
            "解释",
            "说明",
            "说一下",
            "最紧急",
            "优先",
            "急",
            "风险",
            "重要",
            "what are",
            "which",
            "explain",
            "urgent",
            "priority",
            "risk",
        ]
        if any(term in text for term in broad_list_terms) and not any(term in text for term in current_page_question_terms):
            return False
        question_terms = [
            "?",
            "？",
            "吗",
            "么",
            "什么",
            "哪些",
            "分别",
            "解释",
            "说明",
            "说一下",
            "怎么",
            "为什么",
            "要不要",
            "急",
            "重要",
            "风险",
            "优先",
            "下一步",
            "该干嘛",
            "怎么办",
            "what",
            "which",
            "why",
            "how",
            "should",
            "urgent",
            "risk",
            "important",
            "next",
        ]
        return any(term in text for term in question_terms)

    def _looks_like_portfolio_overview(self, text: str) -> bool:
        all_terms = ["所有", "全部", "整体", "总览", "portfolio", "all"]
        client_terms = ["客户", "client", "customer"]
        status_terms = ["情况", "状态", "怎么样", "如何", "overview", "status", "health"]
        return any(term in text for term in all_terms) and any(term in text for term in client_terms) and any(
            term in text for term in status_terms
        )

    def _looks_like_least_urgent_question(self, text: str) -> bool:
        least_terms = ["最不紧急", "最不急", "不紧急", "不急", "晚点", "最后", "least urgent", "lowest priority", "can wait"]
        client_or_work_terms = ["客户", "事项", "任务", "deadline", "ddl", "item", "work"]
        return any(term in text for term in least_terms) and any(term in text for term in client_or_work_terms)


class ClaudeAgentPolicyService:
    """LLM policy layer that decides how this turn should use the work surface."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or os.getenv("claude_api_key")
        self.model = resolve_claude_model(model or os.getenv("CLAUDE_POLICY_MODEL") or os.getenv("CLAUDE_NLU_MODEL"))
        self.fallback = DeterministicAgentPolicyService()

    def decide(self, user_input: str, session: dict[str, Any]) -> AgentPolicyDecision | None:
        deterministic = self.fallback.decide(user_input, session)
        if deterministic and deterministic.render_policy in {"render_new_view", "update_current_view"}:
            return deterministic
        if not self.api_key:
            return deterministic
        raw = self._call_model(self._build_system_prompt(session), user_input)
        try:
            payload = self._extract_json_object(raw)
        except json.JSONDecodeError:
            return deterministic
        decision = AgentPolicyDecision.from_dict(payload)
        if decision.need_type == "pass_to_planner" or decision.render_policy == "pass_to_planner":
            return deterministic
        if decision.render_policy not in {"keep_current_view", "no_view_needed", "render_new_view", "update_current_view"}:
            return deterministic
        if decision.confidence < 0.65:
            return deterministic
        return decision

    def _call_model(self, system_prompt: str, user_input: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 800,
            "temperature": 0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_input}],
        }
        request = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError):
            return '{"need_type":"pass_to_planner","render_policy":"pass_to_planner","confidence":0}'
        parsed = json.loads(raw)
        return "".join(block.get("text", "") for block in parsed.get("content", []) if block.get("type") == "text")

    def _build_system_prompt(self, session: dict[str, Any]) -> str:
        context = {
            "current_view": self._summarize_view(session.get("current_view")),
            "visual_context": session.get("visual_context"),
            "seen_visual_contexts": session.get("seen_visual_contexts", [])[-6:],
            "selectable_items": session.get("selectable_items", [])[:10],
            "current_actions": session.get("current_actions", [])[:5],
            "state_summary": session.get("state_summary"),
            "recent_history": session.get("history_window", [])[-8:],
        }
        return f"""
You are DueDateHQ's agent policy layer.

Decide what the assistant should do THIS TURN before planner/executor runs.
Return only JSON, no markdown.

Schema:
{{
  "need_type": "explain_current_view | answer_advice | change_view | prepare_action | ask_clarifying_question | pass_to_planner",
  "render_policy": "keep_current_view | no_view_needed | update_current_view | render_new_view | pass_to_planner",
  "data_requests": ["current_view | visible_deadlines | all_clients | all_deadlines | client_deadlines | blockers | tasks"],
  "answer_mode": "answer_only | answer_and_render | render_only | pass_to_planner",
  "view_goal": "what the right-side surface should help the user decide, or null",
  "answer": "short user-facing answer if the current context is enough, otherwise null",
  "selected_refs": ["item_1"],
  "next_step": "one concrete next step or null",
  "requires_confirmation": false,
  "confidence": 0.0,
  "reason": "short internal reason"
}}

Policy:
- If the current page already contains the information needed, answer naturally and keep the current view.
- Do not force a new panel just because the user asked a question.
- If the user asks a broad analytical question, such as all-client status, least urgent work, risk ranking, or prioritization,
  choose render_new_view/update_current_view and request only the data needed from the allowed data_requests list.
- If the user is asking to navigate to one known entity or execute an existing workflow, pass_to_planner.
- Never decide to execute a write directly. Use prepare_action/requires_confirmation only as a policy signal.
- The LLM may choose the need and data shape, but the backend will only execute allowed read tools and allowed user actions.
- Keep answers concise but complete enough to reduce cognitive load.

Context:
{json.dumps(context, ensure_ascii=False, indent=2, default=str)}
""".strip()

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
                    "missing": item.get("missing"),
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
