from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from duedatehq.app import create_app  # noqa: E402
from duedatehq.core.flywheel import run_labeled_convergence_test, run_labeled_holdout_test  # noqa: E402
from duedatehq.core.intent_samples import BASIC_FLYWHEEL_SAMPLES  # noqa: E402


def main() -> int:
    with TemporaryDirectory() as tmpdir:
        app = create_app(str(Path(tmpdir) / "flywheel.sqlite3"))
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
        deadline = app.engine.list_deadlines(tenant.tenant_id, client.client_id)[0]
        session = {
            "tenant_id": tenant.tenant_id,
            "today": today.isoformat(),
            "session_id": "flywheel-session",
            "selectable_items": [
                {
                    "ref": "item_1",
                    "deadline_id": deadline.deadline_id,
                    "client_id": client.client_id,
                    "client_name": client.name,
                }
            ],
        }
        full_result = run_labeled_convergence_test(BASIC_FLYWHEEL_SAMPLES, planner=app.intent_planner, session=session)
        holdout_result = run_labeled_holdout_test(BASIC_FLYWHEEL_SAMPLES, planner=app.intent_planner, session=session)
        print(
            json.dumps(
                {
                    "full_replay": asdict(full_result),
                    "holdout": asdict(holdout_result),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
