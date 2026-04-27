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


def test_executor_assigns_step_ids_when_missing(app):
    tenant = _seed_executor_data(app)
    executor = PlanExecutor(app.engine)

    result = executor.execute(
        {
            "plan": [
                {
                    "type": "cli_call",
                    "cli_group": "today",
                    "cli_command": "today",
                    "args": {"tenant_id": tenant.tenant_id, "limit": 5, "enrich": True},
                }
            ],
            "intent_label": "today",
            "op_class": "read",
        }
    )

    assert result["steps_executed"] == ["s1"]
    assert result["meta"]["total"] >= 1


def test_executor_can_call_task_and_blocker_backend_objects(app):
    tenant = _seed_executor_data(app)
    client = app.engine.list_clients(tenant.tenant_id)[0]
    executor = PlanExecutor(app.engine)

    task_result = executor.execute(
        {
            "plan": [
                {
                    "type": "cli_call",
                    "cli_group": "task",
                    "cli_command": "add",
                    "args": {
                        "tenant_id": tenant.tenant_id,
                        "client_id": client.client_id,
                        "title": "Request missing payroll docs",
                        "task_type": "follow_up",
                        "priority": "high",
                    },
                }
            ],
            "intent_label": "task_create",
            "op_class": "write",
        }
    )
    blocker_result = executor.execute(
        {
            "plan": [
                {
                    "type": "cli_call",
                    "cli_group": "blocker",
                    "cli_command": "add",
                    "args": {
                        "tenant_id": tenant.tenant_id,
                        "client_id": client.client_id,
                        "title": "Confirm home jurisdiction",
                        "blocker_type": "missing_info",
                        "source_type": "import",
                    },
                }
            ],
            "intent_label": "blocker_create",
            "op_class": "write",
        }
    )
    bundle_result = executor.execute(
        {
            "plan": [
                {
                    "type": "cli_call",
                    "cli_group": "client",
                    "cli_command": "bundle",
                    "args": {"tenant_id": tenant.tenant_id, "client_id": client.client_id},
                }
            ],
            "intent_label": "client_bundle",
            "op_class": "read",
        }
    )

    assert task_result["final_data"]["status"] == "open"
    assert blocker_result["final_data"]["status"] == "open"
    assert len(bundle_result["final_data"]["tasks"]) == 1
    assert len(bundle_result["final_data"]["blockers"]) == 1


def test_executor_can_generate_notice_work(app):
    tenant = _seed_executor_data(app)
    clients = app.engine.list_clients(tenant.tenant_id)
    executor = PlanExecutor(app.engine)

    result = executor.execute(
        {
            "plan": [
                {
                    "type": "cli_call",
                    "cli_group": "notice",
                    "cli_command": "generate-work",
                    "args": {
                        "tenant_id": tenant.tenant_id,
                        "notice_id": "notice-001",
                        "title": "California filing update",
                        "source_url": "https://example.com/notice",
                        "affected_clients": [
                            {"client_id": clients[0].client_id, "auto_updated": False},
                            {"client_id": clients[1].client_id, "needs_client_confirmation": True},
                        ],
                    },
                }
            ],
            "intent_label": "notice_generate_work",
            "op_class": "write",
        }
    )

    assert len(result["final_data"]["tasks"]) == 1
    assert len(result["final_data"]["blockers"]) == 1
