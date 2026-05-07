from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .engine import InfrastructureEngine


class InteractionMode(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class IntentType(StrEnum):
    TODAY = "today"
    DEADLINES = "deadlines"
    RULE_REVIEW = "rule_review"
    NOTIFICATIONS = "notifications"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ConversationTurn:
    turn_id: str
    actor: str
    mode: InteractionMode
    text: str
    created_at: datetime


@dataclass(slots=True)
class RenderBlock:
    block_type: str
    title: str
    items: list[dict[str, Any]]


@dataclass(slots=True)
class ConversationResponse:
    session_id: str
    intent: IntentType
    reply: str
    render_blocks: list[RenderBlock]
    created_at: datetime


@dataclass(slots=True)
class ConversationSession:
    session_id: str
    tenant_id: str | None
    mode: InteractionMode
    turns: list[ConversationTurn] = field(default_factory=list)


class ConversationService:
    def __init__(self, engine: InfrastructureEngine) -> None:
        self.engine = engine

    def start_session(self, tenant_id: str | None, mode: InteractionMode = InteractionMode.TEXT) -> ConversationSession:
        return ConversationSession(session_id=str(uuid4()), tenant_id=tenant_id, mode=mode)

    def respond(self, session: ConversationSession, text: str, mode: InteractionMode | None = None) -> ConversationResponse:
        interaction_mode = mode or session.mode
        turn = ConversationTurn(
            turn_id=str(uuid4()),
            actor="user",
            mode=interaction_mode,
            text=text.strip(),
            created_at=datetime.now(timezone.utc),
        )
        session.turns.append(turn)
        intent = self._classify_intent(turn.text)
        reply, blocks = self._render_response(session.tenant_id, intent)
        return ConversationResponse(
            session_id=session.session_id,
            intent=intent,
            reply=reply,
            render_blocks=blocks,
            created_at=datetime.now(timezone.utc),
        )

    def _classify_intent(self, text: str) -> IntentType:
        lowered = text.lower()
        if any(token in lowered for token in ["today", "today view", "today's", "今天", "today list"]):
            return IntentType.TODAY
        if any(token in lowered for token in ["deadline", "deadlines", "due", "截止", "到期"]):
            return IntentType.DEADLINES
        if any(token in lowered for token in ["review", "审核", "pending review", "confidence"]):
            return IntentType.RULE_REVIEW
        if any(token in lowered for token in ["notify", "notification", "reminder", "提醒", "通知"]):
            return IntentType.NOTIFICATIONS
        if any(token in lowered for token in ["help", "what can you do", "怎么用", "能干嘛"]):
            return IntentType.HELP
        return IntentType.UNKNOWN

    def _render_response(self, tenant_id: str | None, intent: IntentType) -> tuple[str, list[RenderBlock]]:
        if intent is IntentType.TODAY:
            if not tenant_id:
                return "A tenant is required before I can render the today view.", [self._help_block()]
            deadlines = self.engine.today(tenant_id, limit=10)
            return (
                f"The most important work today is {len(deadlines)} pending deadlines.",
                [
                    RenderBlock(
                        block_type="today",
                        title="Today",
                        items=[
                            {
                                "deadline_id": item.deadline_id,
                                "tax_type": item.tax_type,
                                "jurisdiction": item.jurisdiction,
                                "due_date": item.due_date,
                                "status": item.status.value,
                            }
                            for item in deadlines
                        ],
                    )
                ],
            )
        if intent is IntentType.DEADLINES:
            if not tenant_id:
                return "A tenant is required before I can render the deadline list.", [self._help_block()]
            deadlines = self.engine.list_deadlines(tenant_id)
            return (
                f"There are {len(deadlines)} deadlines.",
                [
                    RenderBlock(
                        block_type="deadlines",
                        title="Deadlines",
                        items=[
                            {
                                "deadline_id": item.deadline_id,
                                "tax_type": item.tax_type,
                                "jurisdiction": item.jurisdiction,
                                "due_date": item.due_date,
                                "status": item.status.value,
                            }
                            for item in deadlines
                        ],
                    )
                ],
            )
        if intent is IntentType.RULE_REVIEW:
            queue = self.engine.list_rule_review_queue()
            return (
                f"There are {len(queue)} rules in the manual review queue.",
                [
                    RenderBlock(
                        block_type="rule_review",
                        title="Rule Review Queue",
                        items=[
                            {
                                "review_id": item.review_id,
                                "source_url": item.source_url,
                                "confidence_score": item.confidence_score,
                            }
                            for item in queue
                        ],
                    )
                ],
            )
        if intent is IntentType.NOTIFICATIONS:
            if not tenant_id:
                return "A tenant is required before I can render notifications.", [self._help_block()]
            pending = self.engine.list_notification_deliveries(tenant_id, pending_only=True)
            history = self.engine.notify_history(tenant_id)
            return (
                f"There are {len(pending)} pending notifications and {len(history)} recent reminder history items.",
                [
                    RenderBlock(
                        block_type="notifications",
                        title="Pending Notifications",
                        items=[
                            {
                                "delivery_id": item.delivery_id,
                                "channel": item.channel.value,
                                "destination": item.destination,
                                "status": item.status.value,
                            }
                            for item in pending
                        ],
                    ),
                    RenderBlock(
                        block_type="reminder_history",
                        title="Recent Reminder History",
                        items=[
                            {
                                "reminder_id": item.reminder_id,
                                "deadline_id": item.deadline_id,
                                "status": item.status.value,
                                "reminder_day": item.reminder_day,
                            }
                            for item in history[:10]
                        ],
                    ),
                ],
            )
        if intent is IntentType.HELP:
            return "You can ask for today, deadlines, review queue, or notifications.", [self._help_block()]
        return "I will show the most useful starting points first.", [self._help_block()]

    def _help_block(self) -> RenderBlock:
        return RenderBlock(
            block_type="help",
            title="Commands",
            items=[
                {"prompt": "today", "description": "Render today's high-priority deadlines"},
                {"prompt": "deadlines", "description": "Render the current deadline list"},
                {"prompt": "review queue", "description": "Render low-confidence rule reviews"},
                {"prompt": "notifications", "description": "Render pending deliveries and reminder history"},
            ],
        )
