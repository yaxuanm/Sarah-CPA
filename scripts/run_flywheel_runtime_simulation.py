from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from duedatehq.app import create_app  # noqa: E402
from duedatehq.core.flywheel_router import FlywheelIntentRouter  # noqa: E402
from duedatehq.core.intent_cache import InMemoryIntentLibrary  # noqa: E402
from duedatehq.core.intent_samples import BASIC_FLYWHEEL_SAMPLES  # noqa: E402


@dataclass(slots=True)
class CountingPlanner:
    wrapped: Any
    calls: int = 0

    def plan(self, text: str, session: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return self.wrapped.plan(text, session)

    def is_confirm(self, text: str) -> bool:
        return self.wrapped.is_confirm(text)

    def is_cancel(self, text: str) -> bool:
        return self.wrapped.is_cancel(text)


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
        "session_id": "runtime-flywheel-session",
        "selectable_items": [
            {
                "ref": "item_1",
                "deadline_id": deadline.deadline_id,
                "client_id": clients[0].client_id,
                "client_name": clients[0].name,
            }
        ],
        "client_names": [client.name for client in clients],
    }


def select_samples(per_intent: int | None):
    if per_intent is None:
        return BASIC_FLYWHEEL_SAMPLES
    grouped: dict[str, list[Any]] = defaultdict(list)
    for sample in BASIC_FLYWHEEL_SAMPLES:
        grouped[sample.expected_intent].append(sample)
    selected = []
    for intent in sorted(grouped):
        selected.extend(grouped[intent][:per_intent])
    return selected


def run_round(router: FlywheelIntentRouter, samples, session: dict[str, Any]) -> dict[str, Any]:
    start = router.snapshot()
    mismatches = []
    for sample in samples:
        plan = router.plan(sample.text, session)
        actual = plan.get("intent_label")
        if actual != sample.expected_intent:
            mismatches.append(
                {
                    "text": sample.text,
                    "expected": sample.expected_intent,
                    "actual": actual,
                    "source": session.get("_last_plan_route", {}).get("source"),
                }
            )
    end = router.snapshot()
    requests = end["total_requests"] - start["total_requests"]
    planner_calls = end["planner_calls"] - start["planner_calls"]
    cache_hits = end["cache_hits"] - start["cache_hits"]
    return {
        "requests": requests,
        "planner_calls": planner_calls,
        "cache_hits": cache_hits,
        "planner_call_rate": planner_calls / requests if requests else 0,
        "cache_hit_rate": cache_hits / requests if requests else 0,
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate runtime flywheel routing and cost reduction.")
    parser.add_argument("--per-intent", type=int, default=None, help="Limit samples per intent. Default: all samples.")
    args = parser.parse_args()

    with TemporaryDirectory() as tmpdir:
        app = create_app(str(Path(tmpdir) / "runtime-flywheel.sqlite3"))
        session = build_session(app)
        expensive_planner = CountingPlanner(app.intent_planner)
        router = FlywheelIntentRouter(
            intent_library=InMemoryIntentLibrary(),
            planner=expensive_planner,
        )
        samples = select_samples(args.per_intent)
        round1 = run_round(router, samples, session)
        round2 = run_round(router, samples, session)

    report = {
        "sample_count": len(samples),
        "round1": round1,
        "round2": round2,
        "planner_calls_total": expensive_planner.calls,
        "template_count": router.snapshot()["template_count"],
        "templates": sorted(template.intent_label for template in router.intent_library.all()),
        "cost_reduction_from_round1_to_round2": (
            1 - (round2["planner_calls"] / round1["planner_calls"])
            if round1["planner_calls"]
            else 0
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
