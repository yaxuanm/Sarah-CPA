from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from .engine import InfrastructureEngine
from .models import DeadlineAction, DeadlineStatus


class PlanExecutionError(RuntimeError):
    pass


class EntityNotFoundError(PlanExecutionError):
    pass


class UnsupportedPlanStepError(PlanExecutionError):
    pass


class PlanExecutor:
    def __init__(self, engine: InfrastructureEngine) -> None:
        self.engine = engine

    def execute(self, plan: dict[str, Any]) -> dict[str, Any]:
        steps = plan.get("plan", [])
        results: dict[str, Any] = {}
        bindings: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        steps_executed: list[str] = []

        for step in steps:
            step_id = step["step_id"]
            depends_on = step.get("depends_on")
            if depends_on and depends_on not in results:
                raise PlanExecutionError(f"dependency step {depends_on} not completed")

            try:
                result = self._execute_step(step, results, bindings, errors)
            except EntityNotFoundError:
                raise
            except Exception as exc:  # pragma: no cover - surfaced as execution_failed to caller
                raise PlanExecutionError(f"step {step_id} failed: {exc}") from exc

            results[step_id] = result
            steps_executed.append(step_id)
            if step.get("bind_as"):
                bindings[step["bind_as"]] = result

        final_data = results[steps[-1]["step_id"]] if steps else []
        meta = {
            "total": len(final_data) if isinstance(final_data, list) else (0 if final_data is None else 1),
            "truncated": False,
        }
        if bindings:
            meta["bindings"] = {key: self._serialize(value) for key, value in bindings.items()}
        return {
            "plan_id": f"plan-{uuid4()}",
            "intent_label": plan.get("intent_label", "unknown"),
            "op_class": plan.get("op_class", "read"),
            "steps_executed": steps_executed,
            "final_data": self._serialize(final_data),
            "meta": meta,
            "errors": errors,
        }

    def _execute_step(
        self,
        step: dict[str, Any],
        results: dict[str, Any],
        bindings: dict[str, Any],
        errors: list[dict[str, Any]],
    ) -> Any:
        step_type = step["type"]
        if step_type == "cli_call":
            return self._execute_cli_call(step, results, bindings)
        if step_type == "resolve_entity":
            return self._resolve_entity(step, bindings)
        if step_type == "post_filter":
            return self._execute_post_filter(step, results)
        if step_type == "foreach":
            return self._execute_foreach(step, results, bindings, errors)
        raise UnsupportedPlanStepError(step_type)

    def _resolve_entity(self, step: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
        if step["entity_type"] != "client":
            raise UnsupportedPlanStepError(f"resolve_entity:{step['entity_type']}")
        args = self._resolve_args(step.get("args", {}), bindings)
        clients = self.engine.list_clients(args["tenant_id"])
        match_field = step.get("match_field", "name")
        entity_name = step["entity_name"].casefold()
        for client in clients:
            if str(getattr(client, match_field)).casefold() == entity_name:
                return self._serialize(client)
        raise EntityNotFoundError(step["entity_name"])

    def _execute_post_filter(self, step: dict[str, Any], results: dict[str, Any]) -> list[Any]:
        source = results[step["depends_on"]]
        if not isinstance(source, list):
            raise PlanExecutionError("post_filter source must be a list")
        filter_spec = step["filter"]
        field = filter_spec["field"]
        value = filter_spec["value"]
        operator = filter_spec.get("operator", "contains")
        return [item for item in source if self._match(self._value_for(item, field), value, operator)]

    def _execute_foreach(
        self,
        step: dict[str, Any],
        results: dict[str, Any],
        bindings: dict[str, Any],
        errors: list[dict[str, Any]],
    ) -> list[Any]:
        source = results[step["depends_on"]]
        if not isinstance(source, list):
            raise PlanExecutionError("foreach source must be a list")

        merged: list[Any] = []
        step_binding_name = step.get("item_alias") or step["depends_on"]
        for item in source[:50]:
            local_bindings = dict(bindings)
            local_bindings[step_binding_name] = item
            try:
                sub_result = self._execute_cli_call(step, results, local_bindings)
            except Exception as exc:
                errors.append({"step_id": step["step_id"], "item": self._serialize(item), "error": str(exc)})
                continue
            if isinstance(sub_result, list):
                merged.extend(sub_result)
            else:
                merged.append(sub_result)
        return merged

    def _execute_cli_call(self, step: dict[str, Any], results: dict[str, Any], bindings: dict[str, Any]) -> Any:
        args = self._resolve_args(step.get("args", {}), bindings)
        cli_group = step["cli_group"]
        cli_command = step["cli_command"]

        if cli_group == "today":
            data = self.engine.today_enriched(args["tenant_id"], args.get("limit", 5)) if args.get("enrich") else self.engine.today(args["tenant_id"], args.get("limit", 5))
            return self._serialize(data)
        if cli_group == "client" and cli_command == "list":
            return self._serialize(self.engine.list_clients(args["tenant_id"]))
        if cli_group == "deadline" and cli_command == "list":
            status = DeadlineStatus(args["status"]) if args.get("status") else None
            data = self.engine.list_deadlines(
                args["tenant_id"],
                args.get("client_id"),
                within_days=args.get("within_days"),
                status=status,
                jurisdiction=args.get("jurisdiction"),
                limit=args.get("limit"),
                offset=args.get("offset", 0),
            )
            return self._serialize(data)
        if cli_group == "deadline" and cli_command == "available-actions":
            return self.engine.available_deadline_actions(args["tenant_id"], args["deadline_id"])
        if cli_group == "deadline" and cli_command == "transitions":
            return self._serialize(self.engine.list_transitions(args["deadline_id"], args["tenant_id"]))
        if cli_group == "deadline" and cli_command == "action":
            metadata: dict[str, Any] = {}
            if "until" in args:
                metadata["until"] = args["until"]
            if "new_date" in args:
                metadata["new_date"] = args["new_date"]
            return self.engine.apply_deadline_action(
                args["tenant_id"],
                args["deadline_id"],
                DeadlineAction(args["action"]),
                args.get("actor", "system"),
                metadata=metadata,
            )
        if cli_group == "notify" and cli_command == "preview":
            return self._serialize(self.engine.notify_preview(args["tenant_id"], args.get("within_days", 7)))
        if cli_group == "notify" and cli_command == "history":
            return self._serialize(self.engine.notify_history(args["tenant_id"]))
        if cli_group == "log" and cli_command == "list":
            return self._serialize(self.engine.list_audit_logs(args.get("tenant_id"), args.get("object_id")))
        if cli_group == "export" and cli_command == "export":
            return self.engine.export_deadlines(args["tenant_id"], actor=args.get("actor", "system"), client_id=args.get("client_id"))
        if cli_group == "rule" and cli_command == "list":
            return self._serialize(self.engine.list_rules())
        if cli_group == "rule" and cli_command == "review-queue":
            return self._serialize(self.engine.list_rule_review_queue())
        raise UnsupportedPlanStepError(f"{cli_group}.{cli_command}")

    def _resolve_args(self, args: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$"):
                binding_name, field = value[1:].split(".", 1)
                resolved[key] = self._value_for(bindings[binding_name], field)
            else:
                resolved[key] = value
        return resolved

    def _match(self, current: Any, expected: Any, operator: str) -> bool:
        if operator == "equals":
            return current == expected
        if operator == "contains":
            if isinstance(current, list):
                return expected in current
            return str(expected).casefold() in str(current).casefold()
        raise PlanExecutionError(f"unsupported filter operator: {operator}")

    def _value_for(self, source: Any, field: str) -> Any:
        current = source
        for part in field.split("."):
            if isinstance(current, dict):
                current = current[part]
            else:
                current = getattr(current, part)
        return current

    def _serialize(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self._serialize(item) for item in value]
        if is_dataclass(value):
            payload = asdict(value)
            return self._serialize(payload)
        if isinstance(value, dict):
            return {key: self._serialize(item) for key, item in value.items()}
        if isinstance(value, datetime):
            return value.isoformat()
        return value
