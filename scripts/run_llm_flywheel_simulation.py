from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from duedatehq.app import create_app  # noqa: E402
from duedatehq.core.flywheel import LabeledFlywheelInput, run_labeled_holdout_test  # noqa: E402
from duedatehq.core.intent_samples import BASIC_FLYWHEEL_SAMPLES  # noqa: E402
from duedatehq.core.nlu_service import DEFAULT_CLAUDE_NLU_MODEL, resolve_claude_model  # noqa: E402


DEFAULT_MODEL = DEFAULT_CLAUDE_NLU_MODEL
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def key_for_intent_samples(samples: list[LabeledFlywheelInput]) -> dict[str, list[str]]:
    by_intent: dict[str, list[str]] = defaultdict(list)
    for sample in samples:
        by_intent[sample.expected_intent].append(sample.text)
    return dict(sorted(by_intent.items()))


def build_prompt(by_intent: dict[str, list[str]], per_intent: int) -> str:
    intent_payload = {
        intent: examples[:12]
        for intent, examples in by_intent.items()
    }
    return f"""
You generate evaluation data for a CPA deadline assistant called DueDateHQ.

Generate {per_intent} NEW user utterances for each intent below. The user is a CPA or CPA firm staff member. Make the expressions realistic, concise, and varied. Include English, Chinese, mixed Chinese/English, partial phrases, vague phrasing, and some edge cases.

Do not duplicate the seed examples. Do not invent new intent labels. Keep every output item labeled with exactly one of the provided intents.
When using a client name, use one of these example clients: Acme, TechCorp, Greenway, Baker, TechVision.

Important safety rule:
- If the utterance negates an action, such as "do not complete", "don't mark done", "先别标记完成", label it as "defer", not as a write action.
- If the utterance asks to view completed/handled items as a list, label it "completed_deadlines".
- If the utterance records the current item as done/sent/handled, label it "deadline_action_complete".
- If a client name appears, such as Acme, and the user asks about that client, label it "client_deadline_list", even if words like today or urgent appear.

Seed examples by intent:
{json.dumps(intent_payload, ensure_ascii=False, indent=2)}

Return ONLY valid JSON in this exact shape:
[
  {{"text": "user utterance", "expected_intent": "intent_label"}}
]
""".strip()


def extract_json_array(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if stripped.startswith("["):
        return json.loads(stripped)
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Claude response did not contain a JSON array")
    return json.loads(stripped[start : end + 1])


def call_claude(prompt: str, *, api_key: str, model: str) -> list[LabeledFlywheelInput]:
    payload = {
        "model": model,
        "max_tokens": 6000,
        "temperature": 0.8,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Claude API request failed with HTTP {exc.code}: {body}") from exc

    parsed = json.loads(raw)
    text = "".join(block.get("text", "") for block in parsed.get("content", []) if block.get("type") == "text")
    items = extract_json_array(text)
    return [
        LabeledFlywheelInput(
            text=str(item["text"]).strip(),
            expected_intent=str(item["expected_intent"]).strip(),
        )
        for item in items
        if item.get("text") and item.get("expected_intent")
    ]


def build_session(app) -> dict[str, Any]:
    tenant = app.engine.create_tenant("Tenant A")
    today = datetime.now(timezone.utc).date()
    app.engine.create_rule(
        tax_type="sales_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=2)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://example.com/rule",
        confidence_score=0.99,
    )
    client = app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="TechCorp LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Greenway Consulting LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Baker Corp",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="TechVision LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
    return {
        "tenant_id": tenant.tenant_id,
        "today": today.isoformat(),
        "session_id": "llm-flywheel-session",
        "selectable_items": [
            {
                "ref": "item_1",
                "deadline_id": deadline.deadline_id,
                "client_id": client.client_id,
                "client_name": client.name,
            }
        ],
        "client_names": ["Acme LLC", "TechCorp LLC", "Greenway Consulting LLC", "Baker Corp", "TechVision LLC"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate LLM simulated intent samples and evaluate flywheel holdout accuracy.")
    parser.add_argument("--per-intent", type=int, default=8)
    parser.add_argument("--model", default=os.getenv("CLAUDE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path for generated samples and metrics.")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or os.getenv("claude_api_key")
    if not api_key:
        raise SystemExit("No Claude API key found. Set ANTHROPIC_API_KEY, CLAUDE_API_KEY, or claude_api_key in .env.")

    by_intent = key_for_intent_samples(BASIC_FLYWHEEL_SAMPLES)
    model = resolve_claude_model(args.model)
    generated = call_claude(build_prompt(by_intent, args.per_intent), api_key=api_key, model=model)
    valid_intents = set(by_intent)
    generated = [item for item in generated if item.expected_intent in valid_intents]

    with TemporaryDirectory() as tmpdir:
        app = create_app(str(Path(tmpdir) / "llm-flywheel.sqlite3"))
        session = build_session(app)
        combined = BASIC_FLYWHEEL_SAMPLES + generated
        holdout = run_labeled_holdout_test(combined, planner=app.intent_planner, session=session)

    report = {
        "model": model,
        "base_samples": len(BASIC_FLYWHEEL_SAMPLES),
        "generated_samples": len(generated),
        "combined_samples": len(combined),
        "generated_by_intent": {intent: sum(1 for item in generated if item.expected_intent == intent) for intent in sorted(valid_intents)},
        "holdout": asdict(holdout),
        "generated_samples_preview": [asdict(item) for item in generated[:20]],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps({**report, "generated_samples": [asdict(item) for item in generated]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
