from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RuleStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    PENDING_REVIEW = "pending_review"


class DeadlineStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    WAIVED = "waived"
    OVERRIDDEN = "overridden"


class ReminderType(StrEnum):
    STANDARD = "standard"
    CRITICAL = "critical"


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    SLACK = "slack"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class DeadlineAction(StrEnum):
    COMPLETE = "complete"
    SNOOZE = "snooze"
    WAIVE = "waive"
    REOPEN = "reopen"
    OVERRIDE = "override"
    RESUME = "resume"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_key: str
    source_type: str
    jurisdiction: str
    official: bool
    poll_frequency_minutes: int
    display_name: str
    default_url: str
    fetch_format: str


@dataclass(slots=True)
class Tenant:
    tenant_id: str
    name: str
    created_at: datetime
    is_deleted: bool = False
    deleted_at: datetime | None = None


@dataclass(slots=True)
class Client:
    client_id: str
    tenant_id: str
    name: str
    entity_type: str
    registered_states: list[str]
    tax_year: int
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class RuleRecord:
    rule_id: str
    tax_type: str
    jurisdiction: str
    entity_types: list[str]
    deadline_date: str
    effective_from: str
    source_url: str
    confidence_score: float
    status: RuleStatus
    version: int
    created_at: datetime
    superseded_by: str | None = None
    raw_text: str | None = None
    fetched_at: datetime | None = None


@dataclass(slots=True)
class RuleReviewItem:
    review_id: str
    source_url: str
    fetched_at: datetime
    raw_text: str
    confidence_score: float
    created_at: datetime
    parse_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FetchRun:
    fetch_run_id: str
    source_key: str
    source_url: str
    fetched_at: datetime
    status: str
    created_at: datetime
    rule_id: str | None = None
    review_id: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class Deadline:
    deadline_id: str
    client_id: str
    tenant_id: str
    rule_id: str
    tax_type: str
    jurisdiction: str
    due_date: str
    status: DeadlineStatus
    reminder_type: ReminderType
    override_date: str | None
    snoozed_until: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class DeadlineTransition:
    transition_id: str
    deadline_id: str
    tenant_id: str
    previous_status: str
    new_status: str
    action: str
    actor: str
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(slots=True)
class Reminder:
    reminder_id: str
    deadline_id: str
    tenant_id: str
    client_id: str
    scheduled_at: datetime
    triggered_at: datetime | None
    status: ReminderStatus
    reminder_day: str
    reminder_type: ReminderType
    responded_at: datetime | None
    response: str | None


@dataclass(slots=True)
class NotificationRoute:
    route_id: str
    tenant_id: str
    channel: NotificationChannel
    destination: str
    enabled: bool
    created_at: datetime


@dataclass(slots=True)
class NotificationDelivery:
    delivery_id: str
    tenant_id: str
    client_id: str
    deadline_id: str
    reminder_id: str
    channel: NotificationChannel
    destination: str
    subject: str
    body: str
    status: NotificationStatus
    provider_message_id: str | None
    error_message: str | None
    created_at: datetime
    sent_at: datetime | None


@dataclass(slots=True)
class AuditRecord:
    log_id: str
    tenant_id: str
    actor: str
    actor_ip: str
    action_type: str
    object_type: str
    object_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    correlation_id: str
    created_at: datetime
