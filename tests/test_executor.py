from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from duedatehq.app import create_app
from duedatehq.core.executor import EntityNotFoundError, PlanExecutor


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "executor.sqlite3"))


def _seed_executor_data(app):
    tenant = app.engine.create_tenant("Tenant A")
    today = datetime.now(timezone.utc).date()
    app.engine.create_rule(
        tax_type="franchise_tax",
        jurisdiction="CA",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=3)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://ftb.ca.gov/r1",
        confidence_score=0.99,
    )
    app.engine.create_rule(
        tax_type="annual_report",
        jurisdiction="DE",
        entity_types=["s-corp"],
        deadline_date=(today + timedelta(days=10)).isoformat(),
        effective_from=today.isoformat(),
        source_url="https://de.gov/r1",
        confidence_score=0.99,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Acme LLC",
        entity_type="s-corp",
        registered_states=["CA", "DE"],
        tax_year=today.year,
    )
    app.engine.register_client(
        tenant_id=tenant.tenant_id,
        name="Beta LLC",
        entity_type="s-corp",
        registered_states=["CA"],
        tax_year=today.year,
    )
    return tenant


def test_executor_resolves_entity_and_lists_client_deadlines(app):
    tenant = _seed_executor_data(app)
    executor = PlanExecutor(app.engine)

    result = executor.execute(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "resolve_entity",
                    "entity_name": "Acme LLC",
                    "entity_type": "client",
                    "args": {"tenant_id": tenant.tenant_id},
                    "match_field": "name",
                    "bind_as": "resolved_client",
                },
                {
                    "step_id": "s2",
                    "type": "cli_call",
                    "cli_group": "deadline",
                    "cli_command": "list",
                    "args": {"tenant_id": tenant.tenant_id, "client_id": "$resolved_client.client_id"},
                    "depends_on": "s1",
                },
            ],
            "intent_label": "client_deadline_list",
            "op_class": "read",
        }
    )

    assert result["intent_label"] == "client_deadline_list"
    assert result["meta"]["total"] == 2
    assert all(item["client_id"] == result["meta"]["bindings"]["resolved_client"]["client_id"] for item in result["final_data"])


def test_executor_post_filter_and_foreach(app):
    tenant = _seed_executor_data(app)
    executor = PlanExecutor(app.engine)

    result = executor.execute(
        {
            "plan": [
                {
                    "step_id": "s1",
                    "type": "cli_call",
                    "cli_group": "client",
                    "cli_command": "list",
                    "args": {"tenant_id": tenant.tenant_id},
                },
                {
                    "step_id": "s2",
                    "type": "post_filter",
                    "depends_on": "s1",
                    "filter": {"field": "registered_states", "value": "DE", "operator": "contains"},
                },
                {
                    "step_id": "s3",
                    "type": "foreach",
                    "depends_on": "s2",
                    "item_alias": "client_item",
                    "cli_group": "deadline",
                    "cli_command": "list",
                    "args": {"tenant_id": tenant.tenant_id, "client_id": "$client_item.client_id"},
                },
            ],
            "intent_label": "deadline_list_by_state",
            "op_class": "read",
        }
    )

    assert result["meta"]["total"] == 2
    assert {item["jurisdiction"] for item in result["final_data"]} == {"CA", "DE"}


def test_executor_raises_entity_not_found(app):
    tenant = _seed_executor_data(app)
    executor = PlanExecutor(app.engine)

    with pytest.raises(EntityNotFoundError):
        executor.execute(
            {
                "plan": [
                    {
                        "step_id": "s1",
                        "type": "resolve_entity",
                        "entity_name": "Missing LLC",
                        "entity_type": "client",
                        "args": {"tenant_id": tenant.tenant_id},
                        "match_field": "name",
                        "bind_as": "resolved_client",
                    }
                ],
                "intent_label": "client_deadline_list",
                "op_class": "read",
            }
        )
