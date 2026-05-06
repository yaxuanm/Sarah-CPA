from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .nlu_service import ANTHROPIC_API_URL, resolve_claude_model


class AIAssistantError(RuntimeError):
    pass


def propose_import_mapping(
    *,
    prompt: str,
    headers: list[str],
    target_fields: list[dict[str, Any]],
    custom_fields: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Map a user's plain-language correction to a constrained import change."""

    if not prompt.strip():
        return {"summary": "No mapping change was requested.", "changes": [], "ai_used": False}

    payload = _call_json_model(
        system_prompt=_import_mapping_prompt(headers, target_fields, custom_fields or []),
        user_input=prompt,
        api_key=api_key,
        model=model,
        max_tokens=900,
    )
    changes = []
    allowed_headers = set(headers)
    allowed_values = {str(field["key"]) for field in target_fields} | {"skip"}
    for item in payload.get("changes", []) or []:
        if not isinstance(item, dict):
            continue
        header = str(item.get("header") or "").strip()
        next_value = str(item.get("next_value") or "").strip()
        custom_field = item.get("custom_field") if isinstance(item.get("custom_field"), dict) else None
        if header not in allowed_headers:
            continue
        if next_value.startswith("custom:"):
            if not custom_field:
                continue
        elif next_value not in allowed_values:
            continue
        changes.append(
            {
                "header": header,
                "next_value": next_value,
                "note": str(item.get("note") or f"{header} will map to {next_value}.")[:240],
                **({"custom_field": _normalize_custom_field(custom_field)} if custom_field else {}),
            }
        )

    return {
        "summary": str(payload.get("summary") or "Suggested mapping change.")[:180],
        "changes": changes[:3],
        "ai_used": True,
    }


def draft_client_followup(
    *,
    work_item: dict[str, Any],
    previous_body: str = "",
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Draft a client-facing follow-up from one selected work item."""

    payload = _call_json_model(
        system_prompt=_followup_prompt(work_item, previous_body),
        user_input="Draft the client follow-up email now.",
        api_key=api_key,
        model=model,
        max_tokens=1000,
    )
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not subject or not body:
        raise AIAssistantError("Claude returned an incomplete follow-up draft")
    return {
        "subject": subject[:180],
        "body": body[:4000],
        "rationale": str(payload.get("rationale") or "")[:320],
        "ai_used": True,
    }


def fallback_import_mapping(prompt: str, headers: list[str], target_fields: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_prompt = _normalize(prompt)
    matched_header = next((header for header in headers if _normalize(header) in normalized_prompt), "")
    if not matched_header:
        return {
            "summary": "I could not tell which CSV column you want to change.",
            "changes": [],
            "ai_used": False,
        }
    if "skip" in normalized_prompt:
        return {
            "summary": f"Skip {matched_header}",
            "changes": [
                {
                    "header": matched_header,
                    "next_value": "skip",
                    "note": "This column will be ignored during import.",
                }
            ],
            "ai_used": False,
        }
    matched_target = next(
        (
            field
            for field in target_fields
            if any(_normalize(str(value)) in normalized_prompt for value in [field.get("key"), field.get("label"), *field.get("aliases", [])])
        ),
        None,
    )
    if not matched_target:
        return {
            "summary": f"I found {matched_header}, but I could not tell which field to map it to.",
            "changes": [],
            "ai_used": False,
        }
    return {
        "summary": f"Remap {matched_header}",
        "changes": [
            {
                "header": matched_header,
                "next_value": matched_target["key"],
                "note": f"{matched_header} will map to {matched_target['label']}.",
            }
        ],
        "ai_used": False,
    }


def fallback_client_followup(work_item: dict[str, Any], previous_body: str = "") -> dict[str, Any]:
    client_name = str(work_item.get("client_name") or "your account")
    tax_type = str(work_item.get("tax_type") or "the filing")
    jurisdiction = str(work_item.get("jurisdiction") or "")
    due_label = str(work_item.get("due_label") or work_item.get("due_date") or "the due date")
    blocker = str(work_item.get("blocker_reason") or "").strip()
    contact_name = str(work_item.get("contact_name") or "there").split(" ")[0]
    days_remaining = int(work_item.get("days_remaining") or 0)
    urgency = (
        f"This is overdue by {abs(days_remaining)} days"
        if days_remaining < 0
        else f"This is due {due_label}"
    )
    ask = (
        f"Please send or confirm: {blocker}."
        if blocker
        else f"Please send any missing support documents or confirm that nothing has changed for {tax_type}."
    )
    suffix = "\n\nI tightened this from the previous draft." if previous_body.strip() else ""
    return {
        "subject": f"{client_name}: information needed for {tax_type}",
        "body": "\n".join(
            [
                f"Hi {contact_name},",
                "",
                f"We are working on {tax_type}{f' - {jurisdiction}' if jurisdiction else ''} for {client_name}. {urgency}.",
                "",
                ask,
                "",
                "Once we have this, we can keep the filing timeline on track.",
                "",
                "Thank you.",
            ]
        )
        + suffix,
        "rationale": "Fallback draft generated from the selected work item context.",
        "ai_used": False,
    }


def _call_json_model(
    *,
    system_prompt: str,
    user_input: str,
    api_key: str | None,
    model: str | None,
    max_tokens: int,
) -> dict[str, Any]:
    resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or os.getenv("claude_api_key")
    if not resolved_key:
        raise AIAssistantError("Claude API key is not configured")
    payload = {
        "model": resolve_claude_model(model or os.getenv("CLAUDE_AGENT_MODEL") or os.getenv("CLAUDE_NLU_MODEL")),
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_input}],
    }
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": resolved_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AIAssistantError(f"Claude API request failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise AIAssistantError(f"Claude API request failed: {exc}") from exc

    parsed = json.loads(raw)
    text = "".join(block.get("text", "") for block in parsed.get("content", []) if block.get("type") == "text")
    return _extract_json_object(text)


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise AIAssistantError("Claude response did not contain JSON")
    parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise AIAssistantError("Claude response JSON must be an object")
    return parsed


def _import_mapping_prompt(headers: list[str], target_fields: list[dict[str, Any]], custom_fields: list[dict[str, Any]]) -> str:
    return f"""
You are DueDateHQ's CSV import mapping assistant for CPA client portfolios.

Return exactly one JSON object:
{{
  "summary": "short user-facing summary",
  "changes": [
    {{
      "header": "one exact CSV header from allowed_headers",
      "next_value": "one allowed field key, skip, or custom:<id>",
      "note": "short explanation",
      "custom_field": {{"id": "snake_case_id", "label": "Field label", "type": "text"}}
    }}
  ]
}}

Rules:
- Use only exact headers from allowed_headers.
- Standard next_value must be one allowed target key or "skip".
- If the user wants to preserve a non-standard column, create custom:<id> and include custom_field.
- Never invent data rows. Only change mapping.
- If the request is unclear, return an empty changes array with a helpful summary.

allowed_headers:
{json.dumps(headers, ensure_ascii=False)}

allowed_target_fields:
{json.dumps(target_fields, ensure_ascii=False)}

existing_custom_fields:
{json.dumps(custom_fields, ensure_ascii=False)}
""".strip()


def _followup_prompt(work_item: dict[str, Any], previous_body: str) -> str:
    return f"""
You draft concise client follow-up emails for a CPA firm.

Return exactly one JSON object:
{{
  "subject": "client-facing subject",
  "body": "plain text email body",
  "rationale": "one short sentence explaining what context was used"
}}

Rules:
- Use only facts in work_item. Do not invent penalties, filing instructions, or legal advice.
- The email should ask for the missing information or confirmation needed to move this work item forward.
- Keep the tone professional, specific, and easy for a client to answer.
- If previous_body exists, improve it rather than simply copying it.
- Do not mention AI.

work_item:
{json.dumps(work_item, ensure_ascii=False, indent=2)}

previous_body:
{previous_body}
""".strip()


def _normalize_custom_field(field: dict[str, Any]) -> dict[str, str]:
    label = str(field.get("label") or field.get("id") or "Custom field").strip()[:80]
    field_id = _normalize(str(field.get("id") or label)).replace(" ", "_").strip("_") or "custom_field"
    field_type = str(field.get("type") or "text")
    if field_type not in {"text", "date", "single_select"}:
        field_type = "text"
    return {"id": field_id, "label": label, "type": field_type}


def _normalize(value: str) -> str:
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in value).split())
