from __future__ import annotations

import argparse
import json
import os
import sys
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
from duedatehq.core.intent_samples import BASIC_FLYWHEEL_SAMPLES  # noqa: E402
from duedatehq.core.nlu_service import ClaudeNLUService, DEFAULT_HAIKU_MODEL  # noqa: E402


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def select_samples(*, per_intent: int | None, include_all: bool):
    if include_all:
        return BASIC_FLYWHEEL_SAMPLES

    grouped: dict[str, list[Any]] = defaultdict(list)
    for sample in BASIC_FLYWHEEL_SAMPLES:
        grouped[sample.expected_intent].append(sample)

    selected = []
    for intent in sorted(grouped):
        selected.extend(grouped[intent][: per_intent or 2])
    return selected


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
    clients = [
        app.engine.register_client(
            tenant_id=tenant.tenant_id,
            name=name,
            entity_type="s-corp",
            registered_states=["CA"],
            tax_year=today.year,
        )
        for name in ["Acme LLC", "TechCorp LLC", "Greenway Consulting LLC", "Baker Corp", "TechVision LLC"]
    ]
    deadline = app.engine.list_deadlines(tenant.tenant_id, clients[0].client_id)[0]
    return {
        "tenant_id": tenant.tenant_id,
        "today": today.isoformat(),
        "session_id": "nlu-eval-session",
        "selectable_items": [
            {
                "ref": "item_1",
                "deadline_id": deadline.deadline_id,
                "client_id": clients[0].client_id,
                "client_name": clients[0].name,
            }
        ],
        "client_names": [client.name for client in clients],
        "history_window": [
            {"actor": "system", "text": "Acme LLC is the current selected item."},
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Claude Haiku NLU Plan JSON against labeled intent samples.")
    parser.add_argument("--model", default=os.getenv("CLAUDE_NLU_MODEL", DEFAULT_HAIKU_MODEL))
    parser.add_argument("--per-intent", type=int, default=2, help="Stratified samples per intent unless --all is used.")
    parser.add_argument("--all", action="store_true", help="Run all local labeled samples.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    samples = select_samples(per_intent=args.per_intent, include_all=args.all)

    with TemporaryDirectory() as tmpdir:
        app = create_app(str(Path(tmpdir) / "nlu-eval.sqlite3"))
        session = build_session(app)
        nlu = ClaudeNLUService(app.engine, model=args.model)

        results = []
        for sample in samples:
            try:
                plan = nlu.plan(sample.text, session)
                actual = plan.get("intent_label", "unknown")
                error = None
            except Exception as exc:  # noqa: BLE001 - evaluation reports model/runtime failures.
                plan = None
                actual = "error"
                error = str(exc)
            results.append(
                {
                    "text": sample.text,
                    "expected": sample.expected_intent,
                    "actual": actual,
                    "ok": actual == sample.expected_intent,
                    "error": error,
                    "plan": plan,
                }
            )

    total = len(results)
    correct = sum(1 for result in results if result["ok"])
    by_intent = {}
    for intent in sorted({result["expected"] for result in results}):
        intent_results = [result for result in results if result["expected"] == intent]
        intent_correct = sum(1 for result in intent_results if result["ok"])
        by_intent[intent] = {
            "total": len(intent_results),
            "correct": intent_correct,
            "accuracy": intent_correct / len(intent_results) if intent_results else 0,
        }

    report = {
        "model": args.model,
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0,
        "by_intent": by_intent,
        "mismatches": [result for result in results if not result["ok"]],
        "samples": [asdict(sample) for sample in samples],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
