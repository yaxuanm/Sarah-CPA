from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PlanValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    op_class: str
    required_args: frozenset[str]
    optional_args: frozenset[str] = frozenset()

    @property
    def allowed_args(self) -> frozenset[str]:
        return self.required_args | self.optional_args


class PlanValidator:
    """Validate model-produced Plan JSON before the executor sees it."""

    ALLOWED_SPECIALS = {"reference_unresolvable", "reopen_unavailable"}

    COMMANDS: dict[tuple[str, str], CommandSpec] = {
        ("today", "today"): CommandSpec("read", frozenset({"tenant_id"}), frozenset({"limit", "enrich"})),
        ("client", "list"): CommandSpec("read", frozenset({"tenant_id"})),
        ("client", "show"): CommandSpec("read", frozenset({"tenant_id", "client_id"})),
        ("client", "bundle"): CommandSpec("read", frozenset({"tenant_id", "client_id"})),
        ("deadline", "list"): CommandSpec(
            "read",
            frozenset({"tenant_id"}),
            frozenset({"client_id", "within_days", "status", "jurisdiction", "limit", "offset"}),
        ),
        ("deadline", "available-actions"): CommandSpec("read", frozenset({"tenant_id", "deadline_id"})),
        ("deadline", "transitions"): CommandSpec("read", frozenset({"tenant_id", "deadline_id"})),
        ("deadline", "action"): CommandSpec(
            "write",
            frozenset({"tenant_id", "deadline_id", "action"}),
            frozenset({"actor", "until", "new_date"}),
        ),
        ("notify", "preview"): CommandSpec("read", frozenset({"tenant_id"}), frozenset({"within_days"})),
        ("notify", "history"): CommandSpec("read", frozenset({"tenant_id"})),
        ("log", "list"): CommandSpec("read", frozenset(), frozenset({"tenant_id", "object_id"})),
        ("export", "export"): CommandSpec("read", frozenset({"tenant_id"}), frozenset({"actor", "client_id"})),
        ("task", "add"): CommandSpec(
            "write",
            frozenset({"tenant_id", "client_id", "title"}),
            frozenset(
                {
                    "description",
                    "task_type",
                    "priority",
                    "source_type",
                    "source_id",
                    "owner_user_id",
                    "due_at",
                    "actor",
                }
            ),
        ),
        ("task", "list"): CommandSpec(
            "read",
            frozenset({"tenant_id"}),
            frozenset({"client_id", "status", "source_type", "limit"}),
        ),
        ("task", "update-status"): CommandSpec(
            "write",
            frozenset({"tenant_id", "task_id", "status"}),
            frozenset({"actor"}),
        ),
        ("blocker", "add"): CommandSpec(
            "write",
            frozenset({"tenant_id", "client_id", "title"}),
            frozenset(
                {
                    "description",
                    "blocker_type",
                    "source_type",
                    "source_id",
                    "owner_user_id",
                    "actor",
                }
            ),
        ),
        ("blocker", "list"): CommandSpec(
            "read",
            frozenset({"tenant_id"}),
            frozenset({"client_id", "status", "source_type", "limit"}),
        ),
        ("blocker", "update-status"): CommandSpec(
            "write",
            frozenset({"tenant_id", "blocker_id", "status"}),
            frozenset({"actor"}),
        ),
        ("notice", "generate-work"): CommandSpec(
            "write",
            frozenset({"tenant_id", "notice_id", "title", "source_url"}),
            frozenset({"source_label", "summary", "affected_clients", "actor"}),
        ),
        ("import", "preview"): CommandSpec("read", frozenset({"csv_path"})),
        ("import", "apply"): CommandSpec(
            "write",
            frozenset({"tenant_id", "csv_path", "tax_year"}),
            frozenset({"default_client_type", "actor"}),
        ),
        ("rule", "list"): CommandSpec("read", frozenset()),
        ("rule", "review-queue"): CommandSpec("read", frozenset()),
    }

    def validate(self, plan: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(plan, dict):
            raise PlanValidationError("plan must be a JSON object")

        special = plan.get("special")
        if special:
            if special not in self.ALLOWED_SPECIALS:
                raise PlanValidationError(f"unsupported special plan: {special}")
            return plan

        op_class = plan.get("op_class")
        if op_class not in {"read", "write"}:
            raise PlanValidationError("op_class must be read or write")

        if not isinstance(plan.get("intent_label"), str) or not plan["intent_label"].strip():
            raise PlanValidationError("intent_label is required")

        steps = plan.get("plan")
        if not isinstance(steps, list) or not steps:
            raise PlanValidationError("plan must contain at least one step")

        step_ids: set[str] = set()
        command_ops: list[str] = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise PlanValidationError(f"step {index} must be an object")
            step_id = str(step.get("step_id") or f"s{index}")
            if step_id in step_ids:
                raise PlanValidationError(f"duplicate step_id: {step_id}")
            command_op = self._validate_step(step, step_ids, index)
            if command_op:
                command_ops.append(command_op)
            step_ids.add(step_id)

        if "write" in command_ops and op_class != "write":
            raise PlanValidationError("write command requires op_class=write")
        if op_class == "write" and "write" not in command_ops:
            raise PlanValidationError("op_class=write requires at least one write command")

        return plan

    def _validate_step(self, step: dict[str, Any], available_step_ids: set[str], index: int) -> str | None:
        step_type = step.get("type")
        if step_type == "cli_call":
            return self._validate_command(step, index)
        if step_type == "foreach":
            depends_on = step.get("depends_on")
            if not isinstance(depends_on, str) or depends_on not in available_step_ids:
                raise PlanValidationError(f"foreach step {index} depends_on must reference an earlier step")
            return self._validate_command(step, index)
        if step_type == "resolve_entity":
            if step.get("entity_type") != "client":
                raise PlanValidationError("resolve_entity only supports entity_type=client")
            args = step.get("args")
            if not isinstance(args, dict) or "tenant_id" not in args:
                raise PlanValidationError("resolve_entity requires args.tenant_id")
            if not isinstance(step.get("entity_name"), str) or not step["entity_name"].strip():
                raise PlanValidationError("resolve_entity requires entity_name")
            return None
        if step_type == "post_filter":
            depends_on = step.get("depends_on")
            if not isinstance(depends_on, str) or depends_on not in available_step_ids:
                raise PlanValidationError(f"post_filter step {index} depends_on must reference an earlier step")
            filter_spec = step.get("filter")
            if not isinstance(filter_spec, dict) or not {"field", "value"} <= set(filter_spec):
                raise PlanValidationError("post_filter requires filter.field and filter.value")
            if filter_spec.get("operator", "contains") not in {"contains", "equals"}:
                raise PlanValidationError("post_filter operator must be contains or equals")
            return None
        raise PlanValidationError(f"unsupported step type: {step_type}")

    def _validate_command(self, step: dict[str, Any], index: int) -> str:
        command_key = (step.get("cli_group"), step.get("cli_command"))
        spec = self.COMMANDS.get(command_key)
        if spec is None:
            raise PlanValidationError(f"unsupported command in step {index}: {command_key[0]}.{command_key[1]}")

        args = step.get("args", {})
        if not isinstance(args, dict):
            raise PlanValidationError(f"step {index} args must be an object")

        missing = spec.required_args - set(args)
        if missing:
            raise PlanValidationError(f"step {index} missing required args: {', '.join(sorted(missing))}")

        unknown = set(args) - spec.allowed_args
        if unknown:
            raise PlanValidationError(f"step {index} has unsupported args: {', '.join(sorted(unknown))}")

        return spec.op_class
