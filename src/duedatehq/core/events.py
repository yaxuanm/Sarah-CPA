from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class EventType(StrEnum):
    TENANT_CREATED = "tenant_created"
    FETCH_COMPLETED = "fetch_completed"
    RULE_CHANGED = "rule_changed"
    DEADLINE_UPDATED = "deadline_updated"
    DEADLINE_STATUS_CHANGED = "deadline_status_changed"
    CLIENT_CREATED = "client_created"
    CLIENT_UPDATED = "client_updated"
    REMINDER_TRIGGERED = "reminder_triggered"
    REMINDER_RESPONDED = "reminder_responded"


@dataclass(frozen=True, slots=True)
class Event:
    event_type: EventType
    payload: dict
    source: str
    correlation_id: str
    timestamp: datetime
    event_id: UUID = field(default_factory=uuid4)
