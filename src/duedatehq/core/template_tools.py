from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from .engine import InfrastructureEngine
from .models import DeadlineStatus


TemplateStatus = Literal["hit", "patch", "miss"]
SlotSource = Literal["db", "api", "cache"]


@dataclass(frozen=True, slots=True)
class SlotSchema:
    name: str
    source: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class SkeletonSchema:
    template_id: str
    component: str
    intent_aliases: tuple[str, ...]
    slots: tuple[SlotSchema, ...]
    description: str
    staging: bool = False


class TemplateRegistry:
    """Small in-process skeleton registry used by the agentic template tools.

    This mirrors the intended registry/skeletons layout without requiring a
    filesystem or vector index for the prototype. Unknown-but-near intents
    return a patch suggestion; true misses create a staging skeleton record.
    """

    def __init__(self) -> None:
        self._skeletons: dict[str, SkeletonSchema] = {
            "client_list": SkeletonSchema(
                template_id="client_list",
                component="ClientListCard",
                intent_aliases=("client_list", "ClientListCard", "customers", "客户列表", "客户总数"),
                slots=(
                    SlotSchema("clients", "clients"),
                    SlotSchema("total", "clients"),
                ),
                description="Client roster and client count.",
            ),
            "deadline_view": SkeletonSchema(
                template_id="deadline_view",
                component="ListCard",
                intent_aliases=("deadline_view", "ListCard", "deadline", "截止日期", "work_queue"),
                slots=(
                    SlotSchema("deadlines", "deadlines"),
                    SlotSchema("period", "cache", required=False),
                ),
                description="Deadline list by entity, period, status, or jurisdiction.",
            ),
            "client_summary": SkeletonSchema(
                template_id="client_summary",
                component="ClientCard",
                intent_aliases=("client_summary", "ClientCard", "client", "客户详情"),
                slots=(
                    SlotSchema("client", "client"),
                    SlotSchema("deadlines", "client_deadlines"),
                ),
                description="One client profile with current deadline context.",
            ),
            "tax_change_radar": SkeletonSchema(
                template_id="tax_change_radar",
                component="TaxChangeRadarCard",
                intent_aliases=("tax_change_radar", "TaxChangeRadarCard", "tax news", "政策变化", "税务变化"),
                slots=(
                    SlotSchema("rules", "rules"),
                    SlotSchema("review_queue", "rule_review_queue"),
                    SlotSchema("notices", "notices"),
                    SlotSchema("deadlines", "deadlines"),
                ),
                description="Rule, notice, and deadline impact radar.",
            ),
            "generated_workspace": SkeletonSchema(
                template_id="generated_workspace",
                component="RenderSpecSurface",
                intent_aliases=("generated_workspace", "RenderSpecSurface", "generated"),
                slots=(SlotSchema("render_spec", "cache"),),
                description="Generated constrained work surface.",
            ),
        }
        self._staging: dict[str, SkeletonSchema] = {}

    def resolve_template(self, intent: str, slots: dict[str, Any]) -> dict[str, Any]:
        normalized = _normalize(intent)
        exact = self._exact_match(normalized)
        if exact:
            return {"status": "hit", "template_id": exact.template_id, "skeleton": _skeleton_payload(exact)}

        nearest, score = self._nearest(normalized)
        if nearest and score >= 0.12:
            requested = {key for key, value in slots.items() if value not in (None, "", [], {})}
            known = {slot.name for slot in nearest.slots}
            additions = sorted(requested - known)
            return {
                "status": "patch",
                "base_template_id": nearest.template_id,
                "diff": {"add_slots": additions, "score": round(score, 3)},
                "skeleton": _skeleton_payload(nearest),
            }

        staging_id = f"staging_{normalized or 'unknown'}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        staging = SkeletonSchema(
            template_id=staging_id,
            component="RenderSpecSurface",
            intent_aliases=(intent,),
            slots=tuple(SlotSchema(name, "cache", required=False) for name in sorted(slots)) or (SlotSchema("brief", "cache", False),),
            description=f"Staging skeleton for unresolved intent: {intent}",
            staging=True,
        )
        self._staging[staging_id] = staging
        return {"status": "miss", "staging_template_id": staging_id, "skeleton": _skeleton_payload(staging)}

    def get(self, template_id: str) -> SkeletonSchema | None:
        return self._skeletons.get(template_id) or self._staging.get(template_id)

    def _exact_match(self, normalized: str) -> SkeletonSchema | None:
        for skeleton in self._skeletons.values():
            ids = {skeleton.template_id, skeleton.component, *skeleton.intent_aliases}
            if normalized in {_normalize(item) for item in ids}:
                return skeleton
        return None

    def _nearest(self, normalized: str) -> tuple[SkeletonSchema | None, float]:
        if not normalized:
            return None, 0.0
        query_tokens = _tokens(normalized)
        best: tuple[SkeletonSchema | None, float] = (None, 0.0)
        for skeleton in self._skeletons.values():
            haystack = " ".join((skeleton.template_id, skeleton.component, skeleton.description, *skeleton.intent_aliases))
            score = _jaccard(query_tokens, _tokens(_normalize(haystack)))
            if score > best[1]:
                best = (skeleton, score)
        return best


class SlotDataFetcher:
    def __init__(self, engine: InfrastructureEngine) -> None:
        self.engine = engine

    def fetch_slot_data(self, template_id: str, slot_name: str, params: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(params.get("tenant_id") or "")
        response_view = params.get("response_view") if isinstance(params.get("response_view"), dict) else {}
        response_data = response_view.get("data") if isinstance(response_view.get("data"), dict) else {}

        if slot_name in response_data:
            return {"value": response_data[slot_name], "source": "cache"}
        if slot_name == "render_spec" and isinstance(response_data.get("render_spec"), dict):
            return {"value": response_data["render_spec"], "source": "cache"}
        if slot_name == "period":
            return {"value": params.get("period") or params.get("today"), "source": "cache"}
        if not tenant_id:
            return {"value": None, "source": "cache"}
        if slot_name in {"clients", "total"}:
            clients = [asdict(client) for client in self.engine.list_clients(tenant_id)]
            return {"value": len(clients) if slot_name == "total" else clients, "source": "db"}
        if slot_name == "client":
            client_id = params.get("client_id") or _first_selectable(params, "client_id")
            if client_id:
                return {"value": asdict(self.engine.get_client(tenant_id, str(client_id))), "source": "db"}
            return {"value": None, "source": "db"}
        if slot_name == "deadlines":
            client_id = params.get("client_id") or _first_selectable(params, "client_id")
            status = DeadlineStatus.PENDING if params.get("status") == "pending" else None
            deadlines = [
                asdict(deadline)
                for deadline in self.engine.list_deadlines(
                    tenant_id,
                    str(client_id) if client_id else None,
                    within_days=int(params["within_days"]) if params.get("within_days") else None,
                    status=status,
                )
            ]
            return {"value": deadlines, "source": "db"}
        if slot_name == "rules":
            return {"value": [asdict(rule) for rule in self.engine.list_rules()], "source": "db"}
        if slot_name == "review_queue":
            return {"value": [asdict(item) for item in self.engine.list_rule_review_queue()], "source": "db"}
        if slot_name == "notices":
            return {"value": [asdict(item) for item in self.engine.list_notices(tenant_id, limit=20)], "source": "db"}
        return {"value": response_data.get(slot_name), "source": "cache"}


class RenderDispatcher:
    def dispatch_render(self, template_id: str, filled_slots: dict[str, Any], *, view: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "render_id": f"render_{uuid4().hex[:12]}",
            "template_id": template_id,
            "filled_slots": filled_slots,
            "view": view,
        }


class TemplateToolset:
    def __init__(self, engine: InfrastructureEngine) -> None:
        self.registry = TemplateRegistry()
        self.fetcher = SlotDataFetcher(engine)
        self.dispatcher = RenderDispatcher()

    def run_render_loop(
        self,
        *,
        intent: str,
        slots: dict[str, Any],
        tenant_id: str,
        session: dict[str, Any],
        response_view: dict[str, Any] | None,
    ) -> dict[str, Any]:
        resolution = self.registry.resolve_template(intent, slots)
        skeleton_payload = resolution.get("skeleton") if isinstance(resolution.get("skeleton"), dict) else {}
        template_id = str(resolution.get("template_id") or resolution.get("base_template_id") or resolution.get("staging_template_id") or intent)
        skeleton = self.registry.get(template_id)
        slot_defs = skeleton.slots if skeleton else tuple(
            SlotSchema(str(item.get("name")), str(item.get("source") or "cache"), bool(item.get("required", True)))
            for item in skeleton_payload.get("slots", [])
            if isinstance(item, dict) and item.get("name")
        )
        params = {
            **slots,
            "tenant_id": tenant_id,
            "today": session.get("today"),
            "selectable_items": session.get("selectable_items", []),
            "response_view": response_view or {},
        }
        filled_slots: dict[str, Any] = {}
        slot_sources: dict[str, SlotSource] = {}
        for slot in slot_defs:
            fetched = self.fetcher.fetch_slot_data(template_id, slot.name, params)
            if slot.required or fetched.get("value") not in (None, "", [], {}):
                filled_slots[slot.name] = fetched.get("value")
                slot_sources[slot.name] = str(fetched.get("source") or "cache")  # type: ignore[assignment]
        render_event = self.dispatcher.dispatch_render(template_id, filled_slots, view=response_view)
        render_event["slot_sources"] = slot_sources
        return {"resolution": resolution, "render_event": render_event}


def _skeleton_payload(skeleton: SkeletonSchema) -> dict[str, Any]:
    return {
        "template_id": skeleton.template_id,
        "component": skeleton.component,
        "description": skeleton.description,
        "staging": skeleton.staging,
        "slots": [asdict(slot) for slot in skeleton.slots],
    }


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("_", " ").replace("-", " ").split())


def _tokens(text: str) -> set[str]:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    for phrase, token in {
        "客户": "client",
        "客户数": "client",
        "截止": "deadline",
        "截止日期": "deadline",
        "税务": "tax",
        "政策": "tax",
        "规则": "tax",
    }.items():
        if phrase in normalized:
            tokens.add(token)
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _first_selectable(params: dict[str, Any], key: str) -> Any:
    selectable = params.get("selectable_items")
    if isinstance(selectable, list):
        for item in selectable:
            if isinstance(item, dict) and item.get(key):
                return item[key]
    return None
