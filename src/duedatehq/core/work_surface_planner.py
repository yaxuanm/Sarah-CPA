from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from .models import DeadlineStatus


@dataclass(slots=True)
class NeedFrame:
    goal: str
    scope: str
    evidence_needed: list[str]
    user_decision_needed: bool
    actionability: str
    data_boundary: str | None = None


@dataclass(slots=True)
class EvidenceSource:
    name: str
    priority: str = "medium"
    params: dict[str, Any] | None = None


@dataclass(slots=True)
class EvidencePlan:
    sources: list[EvidenceSource]
    missing_sources: list[str]
    can_answer_fully: bool


@dataclass(slots=True)
class SurfaceDecision:
    action: str
    reason: str
    surface_kind: str | None = None


@dataclass(slots=True)
class SurfaceSection:
    title: str
    source: str


@dataclass(slots=True)
class ContractButton:
    label: str
    type: str
    operation: dict[str, Any] | None = None
    prompt: str | None = None
    context_keys: list[str] | None = None


@dataclass(slots=True)
class SurfacePlan:
    surface_kind: str
    title: str
    primary_question: str
    sections: list[SurfaceSection]
    data_boundary_notice: str | None
    action_contract: list[ContractButton]


@dataclass(slots=True)
class WorkSurfacePlan:
    need: NeedFrame
    evidence_plan: EvidencePlan
    surface_decision: SurfaceDecision
    surface_plan: SurfacePlan
    evidence: dict[str, Any]


class WorkSurfacePlanner:
    """Plan purpose-built work surfaces between Agent understanding and rendering.

    This is intentionally small for the first slice. It makes the missing layer
    explicit, so long-tail needs are handled by the agent layer first.
    """

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def plan(self, user_input: str, session: dict[str, Any]) -> WorkSurfacePlan | None:
        need = self.interpret_need(user_input, session)
        if need is None:
            return None
        evidence_plan = self.plan_evidence(need)
        evidence = self.collect_evidence(evidence_plan, session)
        decision = self.decide_surface(need, evidence_plan, session)
        surface_plan = self.compose_plan(need, evidence_plan, decision, evidence)
        return WorkSurfacePlan(
            need=need,
            evidence_plan=evidence_plan,
            surface_decision=decision,
            surface_plan=surface_plan,
            evidence=evidence,
        )

    def interpret_need(self, user_input: str, session: dict[str, Any]) -> NeedFrame | None:
        text = user_input.strip().casefold()
        if not text:
            return None
        if not self._looks_like_tax_change_need(text):
            return None
        return NeedFrame(
            goal="了解有无影响当前客户工作的税务变化",
            scope="当前客户列表 + 近期待处理事项",
            evidence_needed=["rule_changes", "review_queue", "notices", "affected_clients", "upcoming_deadlines", "external_tax_news"],
            user_decision_needed=False,
            actionability="monitoring",
            data_boundary="当前没有实时外部税务新闻源；以下结果仅来自内部规则库、规则审核队列、notice 记录和客户 deadline。",
        )

    def _looks_like_tax_change_need(self, text: str) -> bool:
        explicit_terms = [
            "税务新闻",
            "税法新闻",
            "税务变化",
            "税法变化",
            "规则变更",
            "政策变化",
            "政策更新",
            "法规更新",
            "法规变化",
            "税收政策",
            "税务政策",
            "有什么新规",
            "新规",
            "值得关注",
            "tax news",
            "tax change",
            "tax update",
            "policy update",
            "policy change",
            "rule change",
            "regulatory change",
            "notice",
        ]
        if any(term in text for term in explicit_terms):
            return True

        subject_terms = ["政策", "法规", "规则", "税务", "税法", "税收", "policy", "regulation", "rule", "tax"]
        change_terms = ["更新", "变化", "变更", "新闻", "新", "最近", "关注", "update", "change", "news", "recent"]
        return any(term in text for term in subject_terms) and any(term in text for term in change_terms)

    def plan_evidence(self, need: NeedFrame) -> EvidencePlan:
        sources = [
            EvidenceSource("rule_list", "high"),
            EvidenceSource("rule_review_queue", "high"),
            EvidenceSource("notice_list", "medium"),
            EvidenceSource("deadline_list", "medium", {"status": "pending", "limit": 50}),
            EvidenceSource("client_list", "low"),
        ]
        missing_sources = ["external_tax_news"] if "external_tax_news" in need.evidence_needed else []
        return EvidencePlan(
            sources=sources,
            missing_sources=missing_sources,
            can_answer_fully=not missing_sources,
        )

    def decide_surface(self, need: NeedFrame, evidence_plan: EvidencePlan, session: dict[str, Any]) -> SurfaceDecision:
        return SurfaceDecision(
            action="new_surface",
            reason="这是跨客户、跨规则来源的监控需求，当前工作区不足以承载。",
            surface_kind="TaxChangeRadar",
        )

    def compose_plan(
        self,
        need: NeedFrame,
        evidence_plan: EvidencePlan,
        decision: SurfaceDecision,
        evidence: dict[str, Any],
    ) -> SurfacePlan:
        return SurfacePlan(
            surface_kind=decision.surface_kind or "GeneratedWorkspace",
            title="本月税务变化雷达",
            primary_question="有哪些规则变更或 notice 可能影响当前客户？",
            sections=[
                SurfaceSection("数据边界", "data_boundary"),
                SurfaceSection("近期规则变更", "rule_changes"),
                SurfaceSection("待审核规则", "review_queue"),
                SurfaceSection("受影响客户与近期截止日", "affected_clients"),
            ],
            data_boundary_notice=need.data_boundary,
            action_contract=[
                ContractButton(label="查看规则审核队列", type="agent_routed", prompt="查看规则审核队列", context_keys=["review_queue"]),
                ContractButton(label="查看近期截止日", type="agent_routed", prompt="查看所有未来截止日", context_keys=["upcoming_deadlines"]),
            ],
        )

    def collect_evidence(self, evidence_plan: EvidencePlan, session: dict[str, Any]) -> dict[str, Any]:
        tenant_id = session.get("tenant_id")
        evidence: dict[str, Any] = {
            "rules": [],
            "review_queue": [],
            "notices": [],
            "deadlines": [],
            "clients": [],
        }
        if not tenant_id:
            return evidence

        for source in evidence_plan.sources:
            if source.name == "rule_list":
                evidence["rules"] = [self._serialize(item) for item in self.engine.list_rules()]
            elif source.name == "rule_review_queue":
                evidence["review_queue"] = [self._serialize(item) for item in self.engine.list_rule_review_queue()]
            elif source.name == "notice_list" and hasattr(self.engine, "list_notices"):
                evidence["notices"] = [self._serialize(item) for item in self.engine.list_notices(tenant_id, limit=20)]
            elif source.name == "deadline_list":
                evidence["deadlines"] = [
                    self._serialize(item)
                    for item in self.engine.list_deadlines(
                        tenant_id,
                        status=DeadlineStatus.PENDING,
                        limit=int((source.params or {}).get("limit") or 50),
                    )
                ]
            elif source.name == "client_list":
                evidence["clients"] = [self._serialize(item) for item in self.engine.list_clients(tenant_id)]
        return evidence

    def _serialize(self, item: Any) -> dict[str, Any]:
        if is_dataclass(item):
            raw = asdict(item)
        elif isinstance(item, dict):
            raw = dict(item)
        else:
            raw = dict(getattr(item, "__dict__", {}))
        return {key: self._json_safe(value) for key, value in raw.items()}

    def _json_safe(self, value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        return value
