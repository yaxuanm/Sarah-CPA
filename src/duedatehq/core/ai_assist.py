from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_AI_MODEL = "claude-haiku-4-5-20251001"


class AIAssistService:
    """Small AI boundary for demo-critical structured assists.

    The service calls Claude when an Anthropic key is configured. Tests and
    local demos without credentials still get deterministic, data-derived
    output so the UI can exercise the same backend path.
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        self.model = model or os.getenv("DUEDATEHQ_AI_MODEL") or DEFAULT_AI_MODEL

    @property
    def provider_label(self) -> str:
        return "anthropic" if self.api_key else "deterministic-fallback"

    def draft_client_email(self, context: dict[str, Any]) -> dict[str, Any]:
        fallback = self._fallback_client_email(context)
        if not self.api_key:
            return fallback
        prompt = (
            "Draft a concise client email for a CPA deadline management system. "
            "Return JSON with subject and body only. Use the provided facts; do not invent deadlines.\n\n"
            f"Context JSON:\n{json.dumps(context, ensure_ascii=False, default=str)}"
        )
        try:
            parsed = self._call_json(prompt)
        except Exception as exc:  # noqa: BLE001 - keep demo path reliable if provider fails.
            fallback["provider_error"] = str(exc)
            return fallback
        subject = str(parsed.get("subject") or fallback["subject"]).strip()
        body = str(parsed.get("body") or fallback["body"]).strip()
        return {"provider": self.provider_label, "subject": subject, "body": body, "used_context": context}

    def _fallback_client_email(self, context: dict[str, Any]) -> dict[str, Any]:
        client_name = str(context.get("client_name") or "your company")
        contact_name = str(context.get("contact_name") or "there")
        first_name = contact_name.split()[0] if contact_name else "there"
        tax_type = str(context.get("tax_type") or "the filing")
        jurisdiction = str(context.get("jurisdiction") or "").strip()
        due_date = str(context.get("due_date") or "the upcoming deadline")
        blocker = str(context.get("blocker_reason") or "").strip()
        work_label = f"{tax_type} - {jurisdiction}" if jurisdiction else tax_type
        subject = f"{client_name}: information needed for {work_label}"
        ask = (
            f"Please send or confirm the following item: {blocker}."
            if blocker
            else "Please send any missing support documents or confirm that nothing has changed."
        )
        body = "\n".join(
            [
                f"Hi {first_name},",
                "",
                f"We are preparing {work_label} for {client_name}, currently due {due_date}.",
                "",
                ask,
                "",
                "Once we have this, we can keep the filing timeline on track.",
                "",
                "Thank you.",
            ]
        )
        return {"provider": self.provider_label, "subject": subject, "body": body, "used_context": context}

    def _call_json(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "max_tokens": 900,
            "temperature": 0,
            "system": "You return one valid JSON object and no markdown.",
            "messages": [{"role": "user", "content": prompt}],
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
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AI provider failed with HTTP {exc.code}: {body}") from exc
        parsed = json.loads(raw)
        text = "".join(block.get("text", "") for block in parsed.get("content", []) if block.get("type") == "text")
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end < start:
            raise RuntimeError("AI provider did not return JSON")
        result = json.loads(text[start : end + 1])
        if not isinstance(result, dict):
            raise RuntimeError("AI provider JSON must be an object")
        return result
