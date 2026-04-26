from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .engine import InfrastructureEngine
from .intent_cache import InMemoryIntentLibrary
from .plan_validator import PlanValidator


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_SONNET_4_6_MODEL = "claude-sonnet-4-6"
DEFAULT_CLAUDE_NLU_MODEL = DEFAULT_SONNET_4_6_MODEL

MODEL_ALIASES = {
    "haiku": DEFAULT_HAIKU_MODEL,
    "haiku-4.5": DEFAULT_HAIKU_MODEL,
    "haiku-4-5": DEFAULT_HAIKU_MODEL,
    "claude-haiku-4-5": DEFAULT_HAIKU_MODEL,
    "claude-haiku-4.5": DEFAULT_HAIKU_MODEL,
    # Anthropic has not published a Haiku 4.6 API ID yet. Treat common
    # shorthand as "latest available Haiku" instead of sending an invalid ID.
    "haiku-4.6": DEFAULT_HAIKU_MODEL,
    "haiku-4-6": DEFAULT_HAIKU_MODEL,
    "4.6-haiku": DEFAULT_HAIKU_MODEL,
    "4-6-haiku": DEFAULT_HAIKU_MODEL,
    "claude-haiku-4-6": DEFAULT_HAIKU_MODEL,
    "sonnet": DEFAULT_SONNET_4_6_MODEL,
    "sonnet-4.6": DEFAULT_SONNET_4_6_MODEL,
    "sonnet-4-6": DEFAULT_SONNET_4_6_MODEL,
    "4.6-sonnet": DEFAULT_SONNET_4_6_MODEL,
    "4-6-sonnet": DEFAULT_SONNET_4_6_MODEL,
    "claude-sonnet-4.6": DEFAULT_SONNET_4_6_MODEL,
    "claude-sonnet-4-6": DEFAULT_SONNET_4_6_MODEL,
}


def resolve_claude_model(model: str | None) -> str:
    if not model:
        return DEFAULT_CLAUDE_NLU_MODEL
    normalized = "-".join(model.strip().casefold().replace("_", "-").split())
    return MODEL_ALIASES.get(normalized, model.strip())


class NLUServiceError(RuntimeError):
    pass


class ClaudeNLUService:
    """LLM-backed implementation of the same planner boundary used by the MVP."""

    def __init__(
        self,
        engine: InfrastructureEngine,
        *,
        intent_library: InMemoryIntentLibrary | None = None,
        api_key: str | None = None,
        model: str | None = None,
        validator: PlanValidator | None = None,
    ) -> None:
        self.engine = engine
        self.intent_library = intent_library
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or os.getenv("claude_api_key")
        self.model = resolve_claude_model(model or os.getenv("CLAUDE_NLU_MODEL"))
        self.validator = validator or PlanValidator()

    def plan(self, text: str, session: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise NLUServiceError("Claude API key is not configured")

        system_prompt = self._build_system_prompt(session)
        raw_text = self._call_model(system_prompt, text)
        try:
            plan = self._extract_json_object(raw_text)
        except json.JSONDecodeError:
            repaired_text = self._repair_model_output(raw_text)
            plan = self._extract_json_object(repaired_text)
        plan = self._normalize_guidance_plan(plan, session)
        self.validator.validate(plan)

        if self.intent_library is not None and not plan.get("special"):
            self.intent_library.learn(text, plan, session)

        return plan

    def is_confirm(self, text: str) -> bool:
        lowered = text.strip().casefold()
        return lowered in {"确认", "可以", "对", "yes", "y", "confirm", "ok", "okay"} or "确认" in lowered

    def is_cancel(self, text: str) -> bool:
        lowered = text.strip().casefold()
        return lowered in {"取消", "算了", "不用", "no", "n", "cancel"} or "取消" in lowered

    def _call_model(self, system_prompt: str, user_input: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 1200,
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
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise NLUServiceError(f"Claude API request failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise NLUServiceError(f"Claude API request failed: {exc}") from exc

        parsed = json.loads(raw)
        text = "".join(block.get("text", "") for block in parsed.get("content", []) if block.get("type") == "text")
        if not text.strip():
            raise NLUServiceError("Claude API returned no text content")
        return text

    def _repair_model_output(self, raw_text: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 1200,
            "temperature": 0,
            "system": "You repair malformed JSON. Return exactly one valid JSON object and no explanation.",
            "messages": [{"role": "user", "content": raw_text}],
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
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise NLUServiceError(f"Claude JSON repair failed with HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise NLUServiceError(f"Claude JSON repair failed: {exc}") from exc

        parsed = json.loads(raw)
        return "".join(block.get("text", "") for block in parsed.get("content", []) if block.get("type") == "text")

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("{"):
            parsed = json.loads(stripped)
        else:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start == -1 or end == -1 or end < start:
                raise NLUServiceError("Claude response did not contain a JSON object")
            parsed = json.loads(stripped[start : end + 1])
        if not isinstance(parsed, dict):
            raise NLUServiceError("Claude response JSON must be an object")
        return parsed

    def _normalize_guidance_plan(self, plan: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        intent_label = plan.get("intent_label")
        if plan.get("special") or intent_label not in {"help", "defer"}:
            return plan
        if plan.get("plan"):
            return plan

        if intent_label == "help":
            message = "你可以直接问今天先做什么、查看某个客户、完成当前任务，或追问为什么。"
            options = ["今天先做什么", "看第一条", "完成当前任务"]
        else:
            message = "好的，当前任务不做更改。"
            options = ["查看今天的待处理事项", "继续看当前客户"]
        return {
            "special": "reference_unresolvable",
            "intent_label": intent_label,
            "message": plan.get("message") or message,
            "options": plan.get("options") or options,
            "selectable_items": plan.get("selectable_items", session.get("selectable_items", [])),
        }

    def _build_system_prompt(self, session: dict[str, Any]) -> str:
        tenant_id = session.get("tenant_id")
        clients = []
        if tenant_id:
            clients = [
                {"client_id": client.client_id, "name": client.name}
                for client in self.engine.list_clients(tenant_id)
            ]
        context = {
            "tenant_id": tenant_id,
            "today": session.get("today"),
            "selectable_items": session.get("selectable_items", []),
            "current_view": self._summarize_current_view(session.get("current_view")),
            "visual_context": session.get("visual_context"),
            "seen_visual_contexts": session.get("seen_visual_contexts", [])[-6:],
            "state_summary": session.get("state_summary"),
            "clients": clients,
            "recent_history": session.get("history_window", [])[-8:],
        }
        return f"""
You are the NLU planner for DueDateHQ, a CPA deadline assistant.

Convert the user message into Plan JSON. Return ONLY JSON. No markdown, no explanation.

Required normal shape:
{{
  "intent_label": "one_stable_intent_label",
  "op_class": "read" | "write",
  "plan": [
    {{
      "step_id": "s1",
      "type": "cli_call",
      "cli_group": "deadline",
      "cli_command": "list",
      "args": {{}}
    }}
  ]
}}

If the request cannot be resolved safely, return this guidance shape:
{{
  "special": "reference_unresolvable",
  "intent_label": "defer_or_help_or_relevant_label",
  "message": "short user-facing message",
  "options": ["one useful next thing"],
  "selectable_items": []
}}

Critical rules:
- Use only IDs present in session context or the client list. Never invent tenant_id, client_id, deadline_id, task_id, blocker_id, or notice_id.
- Relative references like "this", "that", "current", "刚才", "这个", "第一条" must resolve from selectable_items.
- Short, partial, or fuzzy user references should use visual_context, current_view, seen_visual_contexts, selectable_items, and recent_history before asking the user to clarify.
- If the user says a partial client name such as "brigh", resolve it to the closest visible or recently seen client when there is only one plausible match.
- The current rendered page is part of the conversation state. Use its visible clients, deadlines, drafts, available actions, and selected client to infer what the user means.
- Only return reference_unresolvable when the request remains ambiguous after using visual and conversation context.
- If a write target is unclear, return reference_unresolvable.
- Write operations must use op_class "write". They will be confirmed by the backend before execution.
- Do not turn a negated write into a write plan. "don't mark done", "先别标记完成", and similar requests should become guidance/defer.
- Use defer only when the user explicitly wants to postpone, skip, or avoid changing something. Do not use defer for questions.
- Do not use unsupported commands or unsupported args.
- Prefer these stable intent labels when applicable:
  today, client_deadline_list, deadline_history, deadline_action_complete, defer, help,
  upcoming_deadlines, completed_deadlines, notification_preview, rule_review, client_list,
  task_list, blocker_list, notice_generate_work, import_preview, import_apply.

Intent recipes:
- "今天先做什么", "what should I do first", "哪些待处理", "pending items", "todo list" -> today -> today.today.
- "先看 Acme", "open Greenway" -> client_deadline_list -> deadline.list with the matched client_id.
- "为什么这个还没完成", "source?", "who changed this", "这个来源是什么" -> deadline_history -> deadline.transitions for the selected deadline_id.
- "完成第一条", "mark this done", "已发送，记录一下" -> deadline_action_complete -> deadline.action action=complete for the selected deadline_id.
- "暂时不做", "skip for now", "don't mark it complete" -> defer -> guidance, no write command.
- "help", "你能干嘛", "怎么用" -> help -> guidance, no command.
- "已完成的有哪些", "完成记录", "what's done" -> completed_deadlines -> deadline.list status=completed.
- "未来30天有什么", "upcoming deadlines", "what is coming due" -> upcoming_deadlines -> deadline.list within_days=30 status=pending.
- "通知预览", "follow-up email preview" -> notification_preview -> notify.preview.
- "规则审核队列", "low confidence rules" -> rule_review -> rule.review-queue.
- "客户列表", "all clients" -> client_list -> client.list.

Supported commands:
{self._command_reference()}

Session context:
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()

    def _summarize_current_view(self, view: Any) -> dict[str, Any] | None:
        if not isinstance(view, dict):
            return None
        data = view.get("data") if isinstance(view.get("data"), dict) else {}
        summary: dict[str, Any] = {
            "type": view.get("type"),
            "selectable_items": view.get("selectable_items", [])[:10],
        }
        for key in (
            "title",
            "headline",
            "description",
            "client_name",
            "total",
            "status_label",
            "message",
        ):
            if key in data:
                summary[key] = data[key]
        if isinstance(data.get("items"), list):
            summary["items"] = [
                {
                    "client_name": item.get("client_name"),
                    "deadline_id": item.get("deadline_id"),
                    "tax_type": item.get("tax_type"),
                    "jurisdiction": item.get("jurisdiction"),
                    "due_date": item.get("due_date"),
                    "status": item.get("status"),
                }
                for item in data["items"][:10]
                if isinstance(item, dict)
            ]
        if isinstance(data.get("deadlines"), list):
            summary["deadlines"] = [
                {
                    "client_name": item.get("client_name"),
                    "deadline_id": item.get("deadline_id"),
                    "tax_type": item.get("tax_type"),
                    "jurisdiction": item.get("jurisdiction"),
                    "due_date": item.get("due_date"),
                    "status": item.get("status"),
                    "missing": item.get("missing"),
                }
                for item in data["deadlines"][:10]
                if isinstance(item, dict)
            ]
        if isinstance(data.get("render_spec"), dict):
            spec = data["render_spec"]
            summary["render_spec"] = {
                "title": spec.get("title"),
                "intent_summary": spec.get("intent_summary"),
                "block_types": [
                    block.get("type")
                    for block in spec.get("blocks", [])
                    if isinstance(block, dict)
                ][:10],
            }
        return summary

    def _command_reference(self) -> str:
        lines = []
        for (group, command), spec in sorted(self.validator.COMMANDS.items()):
            required = ", ".join(sorted(spec.required_args)) or "-"
            optional = ", ".join(sorted(spec.optional_args)) or "-"
            lines.append(f"- {group}.{command}: op={spec.op_class}; required={required}; optional={optional}")
        return "\n".join(lines)
