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


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    DISMISSED = "dismissed"


class BlockerStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class NoticeStatus(StrEnum):
    QUEUED = "queued"
    READ = "read"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"
    AUTO_UPDATED = "auto_updated"


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
    client_type: str = "business"
    legal_name: str | None = None
    home_jurisdiction: str | None = None
    primary_contact_name: str | None = None
    primary_contact_email: str | None = None
    primary_contact_phone: str | None = None
    preferred_communication_channel: str | None = None
    responsible_cpa: str | None = None
    is_active: bool = True


@dataclass(slots=True)
class ClientTaxProfile:
    profile_id: str
    tenant_id: str
    client_id: str
    tax_year: int
    entity_election: str | None
    first_year_filing: bool | None
    final_year_filing: bool | None
    extension_requested: bool | None
    extension_filed: bool | None
    estimated_tax_required: bool | None
    payroll_present: bool | None
    contractor_reporting_required: bool | None
    notice_received: bool | None
    intake_status: str
    source: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ClientJurisdiction:
    client_jurisdiction_id: str
    tenant_id: str
    client_id: str
    tax_year: int
    jurisdiction: str
    jurisdiction_type: str
    active: bool
    source: str
    notes: str | None
    created_at: datetime


@dataclass(slots=True)
class ClientContact:
    contact_id: str
    tenant_id: str
    client_id: str
    name: str
    role: str | None
    email: str | None
    phone: str | None
    preferred_channel: str | None
    is_primary: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class Task:
    task_id: str
    tenant_id: str
    client_id: str
    title: str
    description: str | None
    task_type: str
    status: TaskStatus
    priority: str
    source_type: str
    source_id: str | None
    owner_user_id: str | None
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    dismissed_at: datetime | None = None


@dataclass(slots=True)
class Blocker:
    blocker_id: str
    tenant_id: str
    client_id: str
    title: str
    description: str | None
    blocker_type: str
    status: BlockerStatus
    source_type: str
    source_id: str | None
    owner_user_id: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    dismissed_at: datetime | None = None


@dataclass(slots=True)
class NoticeRecord:
    notice_id: str
    tenant_id: str
    title: str
    source_url: str
    source_label: str | None
    summary: str | None
    status: NoticeStatus
    created_at: datetime
    updated_at: datetime
    read_at: datetime | None = None
    dismissed_at: datetime | None = None


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
