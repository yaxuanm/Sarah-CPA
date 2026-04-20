from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .bus import InMemoryEventBus
from .clock import Clock
from .events import Event, EventType
from .models import (
    AuditRecord,
    Client,
    Deadline,
    DeadlineAction,
    DeadlineStatus,
    DeadlineTransition,
    Reminder,
    ReminderStatus,
    ReminderType,
    FetchRun,
    RuleRecord,
    RuleReviewItem,
    RuleStatus,
    Tenant,
)
from .repositories import Repositories
from .sources import official_source_registry, source_for_selector
from ..layers.state_machine import DeadlineStateMachine


FEDERAL_JURISDICTION = "FEDERAL"


@dataclass(slots=True)
class RuleParseResult:
    tax_type: str | None
    jurisdiction: str | None
    entity_types: list[str]
    deadline_date: str | None
    effective_from: str | None
    confidence_score: float
    extracted_fields: dict[str, object]


@dataclass(slots=True)
class InfrastructureEngine:
    repositories: Repositories
    event_bus: InMemoryEventBus
    clock: Clock
    state_machine: DeadlineStateMachine = field(default_factory=DeadlineStateMachine)

    def _connect(self, tenant_id: str | None = None):
        return self.repositories.storage.connect(tenant_id=tenant_id)

    def _transaction(self, tenant_id: str | None = None):
        return self.repositories.storage.transaction(tenant_id=tenant_id)

    def create_tenant(self, name: str) -> Tenant:
        tenant = Tenant(tenant_id=str(uuid4()), name=name, created_at=self.clock.now())
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO tenants (tenant_id, name, created_at, is_deleted, deleted_at) VALUES (?, ?, ?, 0, NULL)",
                (tenant.tenant_id, tenant.name, tenant.created_at.isoformat()),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant.tenant_id,
                actor="system",
                actor_ip="127.0.0.1",
                action_type="tenant_created",
                object_type="tenant",
                object_id=tenant.tenant_id,
                before={},
                after={"name": name},
                correlation_id=str(uuid4()),
            )
        self._publish(EventType.TENANT_CREATED, {"tenant_id": tenant.tenant_id, "name": tenant.name}, "system")
        return tenant

    def register_client(
        self,
        tenant_id: str,
        name: str,
        entity_type: str,
        registered_states: list[str],
        tax_year: int,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Client:
        now = self.clock.now()
        client = Client(
            client_id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            entity_type=entity_type.lower(),
            registered_states=sorted({state.upper() for state in registered_states}),
            tax_year=tax_year,
            created_at=now,
            updated_at=now,
        )
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO clients (
                    client_id, tenant_id, name, entity_type, registered_states, tax_year, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client.client_id,
                    client.tenant_id,
                    client.name,
                    client.entity_type,
                    self.repositories.storage.encode_json(client.registered_states),
                    client.tax_year,
                    client.created_at.isoformat(),
                    client.updated_at.isoformat(),
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="client_created",
                object_type="client",
                object_id=client.client_id,
                before={},
                after={
                    "name": client.name,
                    "entity_type": client.entity_type,
                    "registered_states": client.registered_states,
                    "tax_year": client.tax_year,
                },
                correlation_id=correlation_id,
            )
            self._upsert_deadlines_for_client(conn, client, correlation_id, actor, actor_ip)
        self._publish(
            EventType.CLIENT_CREATED,
            {"tenant_id": tenant_id, "client_id": client.client_id, "entity_type": client.entity_type},
            actor,
        )
        return client

    def update_client_states(
        self,
        tenant_id: str,
        client_id: str,
        registered_states: list[str],
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Client:
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM clients WHERE tenant_id = ? AND client_id = ?",
                (tenant_id, client_id),
            ).fetchone()
            if row is None:
                raise KeyError(client_id)
            normalized_states = sorted({state.upper() for state in registered_states})
            now = self.clock.now()
            conn.execute(
                "UPDATE clients SET registered_states = ?, updated_at = ? WHERE client_id = ?",
                (self.repositories.storage.encode_json(normalized_states), now.isoformat(), client_id),
            )
            client = self._client_from_row(
                {
                    **dict(row),
                    "registered_states": self.repositories.storage.encode_json(normalized_states),
                    "updated_at": now.isoformat(),
                }
            )
            correlation_id = str(uuid4())
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="client_updated",
                object_type="client",
                object_id=client_id,
                before={"registered_states": json.loads(row["registered_states"])},
                after={"registered_states": normalized_states},
                correlation_id=correlation_id,
            )
            self._upsert_deadlines_for_client(conn, client, correlation_id, actor, actor_ip)
        self._publish(
            EventType.CLIENT_UPDATED,
            {"tenant_id": tenant_id, "client_id": client_id, "registered_states": normalized_states},
            actor,
        )
        return client

    def parse_rule_text(self, raw_text: str) -> RuleParseResult:
        def extract(label: str) -> str | None:
            match = re.search(rf"{label}\s*:\s*(.+)", raw_text, re.IGNORECASE)
            return match.group(1).strip() if match else None

        tax_type = extract("tax[_ ]type")
        jurisdiction = extract("jurisdiction")
        entity_types_raw = extract("entity[_ ]types")
        deadline_date = extract("deadline[_ ]date")
        effective_from = extract("effective[_ ]from")
        entity_types = [part.strip().lower() for part in entity_types_raw.split(",")] if entity_types_raw else []
        confidence = 0.25 + sum(bool(value) for value in [tax_type, jurisdiction, entity_types, deadline_date, effective_from]) * 0.15
        if re.search(r"\b(irs|ftb|tax|deadline|due date)\b", raw_text, re.IGNORECASE):
            confidence += 0.1
        return RuleParseResult(
            tax_type=tax_type.lower() if tax_type else None,
            jurisdiction=jurisdiction.upper() if jurisdiction else None,
            entity_types=entity_types,
            deadline_date=deadline_date,
            effective_from=effective_from,
            confidence_score=min(confidence, 0.99),
            extracted_fields={
                "tax_type": tax_type.lower() if tax_type else None,
                "jurisdiction": jurisdiction.upper() if jurisdiction else None,
                "entity_types": entity_types,
                "deadline_date": deadline_date,
                "effective_from": effective_from,
            },
        )

    def ingest_rule_text(
        self,
        raw_text: str,
        source_url: str,
        fetched_at: datetime,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> RuleRecord | RuleReviewItem:
        parsed = self.parse_rule_text(raw_text)
        if parsed.confidence_score < 0.85 or not all(
            [parsed.tax_type, parsed.jurisdiction, parsed.entity_types, parsed.deadline_date, parsed.effective_from]
        ):
            return self._queue_rule_review(parsed, raw_text, source_url, fetched_at)
        return self.create_rule(
            tax_type=parsed.tax_type,
            jurisdiction=parsed.jurisdiction,
            entity_types=parsed.entity_types,
            deadline_date=parsed.deadline_date,
            effective_from=parsed.effective_from,
            source_url=source_url,
            confidence_score=parsed.confidence_score,
            raw_text=raw_text,
            fetched_at=fetched_at,
            actor=actor,
            actor_ip=actor_ip,
        )

    def fetch_from_source(
        self,
        *,
        source: str | None = None,
        state: str | None = None,
        raw_text: str,
        source_url: str,
        fetched_at: datetime,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> dict[str, object]:
        source_definition = source_for_selector(source=source, state=state)
        result = self.ingest_rule_text(
            raw_text=raw_text,
            source_url=source_url,
            fetched_at=fetched_at,
            actor=actor,
            actor_ip=actor_ip,
        )
        fetch_run = FetchRun(
            fetch_run_id=str(uuid4()),
            source_key=source_definition.source_key,
            source_url=source_url,
            fetched_at=fetched_at,
            status="review_queued" if isinstance(result, RuleReviewItem) else "rule_written",
            created_at=self.clock.now(),
            rule_id=getattr(result, "rule_id", None),
            review_id=getattr(result, "review_id", None),
            notes=None,
        )
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO fetch_runs (
                    fetch_run_id, source_key, source_url, fetched_at, status, created_at, rule_id, review_id, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fetch_run.fetch_run_id,
                    fetch_run.source_key,
                    fetch_run.source_url,
                    fetch_run.fetched_at.isoformat(),
                    fetch_run.status,
                    fetch_run.created_at.isoformat(),
                    fetch_run.rule_id,
                    fetch_run.review_id,
                    fetch_run.notes,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id="system",
                actor=actor,
                actor_ip=actor_ip,
                action_type="fetch_completed",
                object_type="fetch_run",
                object_id=fetch_run.fetch_run_id,
                before={},
                after={"source_key": fetch_run.source_key, "status": fetch_run.status, "source_url": fetch_run.source_url},
                correlation_id=str(uuid4()),
            )
        self._publish(
            EventType.FETCH_COMPLETED,
            {
                "fetch_run_id": fetch_run.fetch_run_id,
                "source_key": fetch_run.source_key,
                "status": fetch_run.status,
                "rule_id": fetch_run.rule_id,
                "review_id": fetch_run.review_id,
            },
            actor,
        )
        return {
            "fetch_run": fetch_run,
            "result": result,
        }

    def create_rule(
        self,
        *,
        tax_type: str,
        jurisdiction: str,
        entity_types: list[str],
        deadline_date: str,
        effective_from: str,
        source_url: str,
        confidence_score: float,
        raw_text: str | None = None,
        fetched_at: datetime | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> RuleRecord:
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction() as conn:
            previous = conn.execute(
                """
                SELECT * FROM rules
                WHERE jurisdiction = ? AND tax_type = ? AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (jurisdiction.upper(), tax_type.lower()),
            ).fetchone()
            version = 1 if previous is None else previous["version"] + 1
            rule = RuleRecord(
                rule_id=str(uuid4()),
                tax_type=tax_type.lower(),
                jurisdiction=jurisdiction.upper(),
                entity_types=[entity.lower() for entity in entity_types],
                deadline_date=deadline_date,
                effective_from=effective_from,
                source_url=source_url,
                confidence_score=confidence_score,
                status=RuleStatus.ACTIVE,
                version=version,
                created_at=now,
                superseded_by=None,
                raw_text=raw_text,
                fetched_at=fetched_at,
            )
            conn.execute(
                """
                INSERT INTO rules (
                    rule_id, tax_type, jurisdiction, entity_types, deadline_date, effective_from,
                    source_url, confidence_score, status, version, created_at, superseded_by, raw_text, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.rule_id,
                    rule.tax_type,
                    rule.jurisdiction,
                    self.repositories.storage.encode_json(rule.entity_types),
                    rule.deadline_date,
                    rule.effective_from,
                    rule.source_url,
                    rule.confidence_score,
                    rule.status.value,
                    rule.version,
                    rule.created_at.isoformat(),
                    None,
                    rule.raw_text,
                    rule.fetched_at.isoformat() if rule.fetched_at else None,
                ),
            )
            if previous is not None:
                conn.execute(
                    "UPDATE rules SET status = ?, superseded_by = ? WHERE rule_id = ?",
                    (RuleStatus.SUPERSEDED.value, rule.rule_id, previous["rule_id"]),
                )
            self._insert_audit(
                conn=conn,
                tenant_id="system",
                actor=actor,
                actor_ip=actor_ip,
                action_type="rule_changed",
                object_type="rule",
                object_id=rule.rule_id,
                before={} if previous is None else {"rule_id": previous["rule_id"], "deadline_date": previous["deadline_date"]},
                after={"tax_type": rule.tax_type, "jurisdiction": rule.jurisdiction, "deadline_date": rule.deadline_date},
                correlation_id=correlation_id,
            )
            self._refresh_deadlines_for_rule(conn, rule, correlation_id, actor, actor_ip)
        self._publish(
            EventType.RULE_CHANGED,
            {"rule_id": rule.rule_id, "jurisdiction": rule.jurisdiction, "deadline_date": rule.deadline_date},
            actor,
        )
        return rule

    def list_rules(self) -> list[RuleRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM rules ORDER BY created_at DESC").fetchall()
        return [self._rule_from_row(dict(row)) for row in rows]

    def list_deadlines(self, tenant_id: str, client_id: str | None = None) -> list[Deadline]:
        query = "SELECT * FROM deadlines WHERE tenant_id = ?"
        params: list[object] = [tenant_id]
        if client_id:
            query += " AND client_id = ?"
            params.append(client_id)
        query += " ORDER BY due_date, created_at"
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._deadline_from_row(dict(row)) for row in rows]

    def get_deadline(self, tenant_id: str, deadline_id: str) -> Deadline:
        with self._connect(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM deadlines WHERE tenant_id = ? AND deadline_id = ?",
                (tenant_id, deadline_id),
            ).fetchone()
        if row is None:
            raise KeyError(deadline_id)
        return self._deadline_from_row(dict(row))

    def apply_deadline_action(
        self,
        tenant_id: str,
        deadline_id: str,
        action: DeadlineAction,
        actor: str,
        metadata: dict | None = None,
        actor_ip: str = "127.0.0.1",
    ) -> dict[str, object]:
        metadata = metadata or {}
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM deadlines WHERE tenant_id = ? AND deadline_id = ?",
                (tenant_id, deadline_id),
            ).fetchone()
            if row is None:
                raise KeyError(deadline_id)
            deadline = self._deadline_from_row(dict(row))
            new_status = self.state_machine.transition(deadline.status, action)
            due_date = deadline.due_date
            override_date = deadline.override_date
            snoozed_until = None
            if action is DeadlineAction.SNOOZE:
                until = metadata.get("until")
                if not until:
                    raise ValueError("snooze requires until")
                snoozed_until = self._parse_datetime(until)
            elif action is DeadlineAction.OVERRIDE:
                due_date = str(metadata["new_date"])
                override_date = due_date
            conn.execute(
                """
                UPDATE deadlines
                SET status = ?, due_date = ?, override_date = ?, snoozed_until = ?, updated_at = ?
                WHERE deadline_id = ?
                """,
                (
                    new_status.value,
                    due_date,
                    override_date,
                    snoozed_until.isoformat() if snoozed_until else None,
                    now.isoformat(),
                    deadline_id,
                ),
            )
            self._insert_transition(conn, deadline, new_status, action, actor, metadata, now)
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="status_changed",
                object_type="deadline",
                object_id=deadline_id,
                before={"status": deadline.status.value, "due_date": deadline.due_date, "override_date": deadline.override_date},
                after={"status": new_status.value, "due_date": due_date, "override_date": override_date},
                correlation_id=correlation_id,
            )
            if new_status in {DeadlineStatus.COMPLETED, DeadlineStatus.WAIVED}:
                conn.execute(
                    """
                    UPDATE reminders
                    SET status = ?, response = ?, responded_at = ?
                    WHERE deadline_id = ? AND status = ?
                    """,
                    (ReminderStatus.CANCELLED.value, new_status.value, now.isoformat(), deadline_id, ReminderStatus.SCHEDULED.value),
                )
            elif action in {DeadlineAction.OVERRIDE, DeadlineAction.REOPEN, DeadlineAction.RESUME}:
                updated_deadline = Deadline(
                    deadline_id=deadline.deadline_id,
                    client_id=deadline.client_id,
                    tenant_id=deadline.tenant_id,
                    rule_id=deadline.rule_id,
                    tax_type=deadline.tax_type,
                    jurisdiction=deadline.jurisdiction,
                    due_date=due_date,
                    status=new_status,
                    reminder_type=deadline.reminder_type,
                    override_date=override_date,
                    snoozed_until=snoozed_until,
                    created_at=deadline.created_at,
                    updated_at=now,
                )
                self._rebuild_reminders(conn, updated_deadline)
        self._publish(
            EventType.DEADLINE_STATUS_CHANGED,
            {"tenant_id": tenant_id, "deadline_id": deadline_id, "action": action.value, "new_status": new_status.value},
            actor,
        )
        return {
            "deadline_id": deadline_id,
            "previous_status": deadline.status.value,
            "new_status": new_status.value,
            "actor": actor,
            "timestamp": now.isoformat(),
            "metadata": metadata,
        }

    def resume_due_snoozes(self, now: datetime | None = None) -> int:
        now = now or self.clock.now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT deadline_id, tenant_id
                FROM deadlines
                WHERE status = ? AND snoozed_until IS NOT NULL AND snoozed_until <= ?
                """,
                (DeadlineStatus.SNOOZED.value, now.isoformat()),
            ).fetchall()
        for row in rows:
            self.apply_deadline_action(row["tenant_id"], row["deadline_id"], DeadlineAction.RESUME, "system", {"auto": True})
        return len(rows)

    def rebuild_reminders(self, tenant_id: str, deadline_id: str) -> None:
        deadline = self.get_deadline(tenant_id, deadline_id)
        with self._transaction(tenant_id=tenant_id) as conn:
            self._rebuild_reminders(conn, deadline)

    def list_reminders(
        self,
        tenant_id: str,
        deadline_id: str | None = None,
        *,
        include_history: bool = False,
    ) -> list[Reminder]:
        query = "SELECT * FROM reminders WHERE tenant_id = ?"
        params: list[object] = [tenant_id]
        if deadline_id:
            query += " AND deadline_id = ?"
            params.append(deadline_id)
        if not include_history:
            query += " AND status != ?"
            params.append(ReminderStatus.CANCELLED.value)
        query += " ORDER BY scheduled_at"
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._reminder_from_row(dict(row)) for row in rows]

    def trigger_due_reminders(self, now: datetime | None = None) -> int:
        now = now or self.clock.now()
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status = ? AND scheduled_at <= ? ORDER BY scheduled_at",
                (ReminderStatus.SCHEDULED.value, now.isoformat()),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE reminders SET status = ?, triggered_at = ? WHERE reminder_id = ?",
                    (ReminderStatus.TRIGGERED.value, now.isoformat(), row["reminder_id"]),
                )
                self._publish(
                    EventType.REMINDER_TRIGGERED,
                    {"tenant_id": row["tenant_id"], "deadline_id": row["deadline_id"], "reminder_id": row["reminder_id"]},
                    "scheduler",
                )
        return len(rows)

    def export_deadlines(self, tenant_id: str, actor: str, actor_ip: str = "127.0.0.1") -> list[dict[str, object]]:
        deadlines = self.list_deadlines(tenant_id)
        payload = [
            {
                "deadline_id": deadline.deadline_id,
                "client_id": deadline.client_id,
                "tax_type": deadline.tax_type,
                "jurisdiction": deadline.jurisdiction,
                "due_date": deadline.due_date,
                "status": deadline.status.value,
            }
            for deadline in deadlines
        ]
        with self._transaction(tenant_id=tenant_id) as conn:
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="export",
                object_type="deadline",
                object_id=tenant_id,
                before={},
                after={"count": len(payload)},
                correlation_id=str(uuid4()),
            )
        return payload

    def list_transitions(self, deadline_id: str, tenant_id: str | None = None) -> list[DeadlineTransition]:
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(
                "SELECT * FROM deadline_transitions WHERE deadline_id = ? ORDER BY created_at",
                (deadline_id,),
            ).fetchall()
        return [
            DeadlineTransition(
                transition_id=row["transition_id"],
                deadline_id=row["deadline_id"],
                tenant_id=row["tenant_id"],
                previous_status=row["previous_status"],
                new_status=row["new_status"],
                action=row["action"],
                actor=row["actor"],
                metadata=json.loads(row["metadata"]),
                created_at=self._parse_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def list_audit_logs(self, tenant_id: str | None = None, object_id: str | None = None) -> list[AuditRecord]:
        query = "SELECT * FROM audit_log WHERE 1 = 1"
        params: list[object] = []
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        if object_id:
            query += " AND object_id = ?"
            params.append(object_id)
        query += " ORDER BY created_at"
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            AuditRecord(
                log_id=row["log_id"],
                tenant_id=row["tenant_id"],
                actor=row["actor"],
                actor_ip=row["actor_ip"],
                action_type=row["action_type"],
                object_type=row["object_type"],
                object_id=row["object_id"],
                before=json.loads(row["before_json"]),
                after=json.loads(row["after_json"]),
                correlation_id=row["correlation_id"],
                created_at=self._parse_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def list_clients(self, tenant_id: str) -> list[Client]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM clients WHERE tenant_id = ? ORDER BY created_at", (tenant_id,)).fetchall()
        return [self._client_from_row(dict(row)) for row in rows]

    def list_rule_review_queue(self) -> list[RuleReviewItem]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM rule_review_queue ORDER BY created_at DESC").fetchall()
        return [self._review_from_row(dict(row)) for row in rows]

    def list_fetch_runs(self) -> list[FetchRun]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM fetch_runs ORDER BY created_at DESC").fetchall()
        return [
            FetchRun(
                fetch_run_id=row["fetch_run_id"],
                source_key=row["source_key"],
                source_url=row["source_url"],
                fetched_at=self._parse_datetime(row["fetched_at"]),
                status=row["status"],
                created_at=self._parse_datetime(row["created_at"]),
                rule_id=row["rule_id"],
                review_id=row["review_id"],
                notes=row["notes"],
            )
            for row in rows
        ]

    def list_sources(self) -> list[dict[str, object]]:
        return [asdict(definition) for definition in official_source_registry().values()]

    def today(self, tenant_id: str, limit: int = 5) -> list[Deadline]:
        deadlines = [
            deadline
            for deadline in self.list_deadlines(tenant_id)
            if deadline.status in {DeadlineStatus.PENDING, DeadlineStatus.SNOOZED, DeadlineStatus.OVERRIDDEN}
        ]
        deadlines.sort(key=lambda item: (item.due_date, item.created_at))
        return deadlines[:limit]

    def notify_preview(self, tenant_id: str, within_days: int = 7) -> list[Reminder]:
        now = self.clock.now()
        cutoff = now + timedelta(days=within_days)
        reminders = [
            reminder
            for reminder in self.list_reminders(tenant_id)
            if reminder.status is ReminderStatus.SCHEDULED and reminder.scheduled_at <= cutoff
        ]
        reminders.sort(key=lambda item: item.scheduled_at)
        return reminders

    def notify_history(self, tenant_id: str) -> list[Reminder]:
        reminders = [
            reminder
            for reminder in self.list_reminders(tenant_id, include_history=True)
            if reminder.status in {ReminderStatus.TRIGGERED, ReminderStatus.CANCELLED}
        ]
        reminders.sort(key=lambda item: item.scheduled_at)
        return reminders

    def _queue_rule_review(
        self,
        parsed: RuleParseResult,
        raw_text: str,
        source_url: str,
        fetched_at: datetime,
    ) -> RuleReviewItem:
        item = RuleReviewItem(
            review_id=str(uuid4()),
            source_url=source_url,
            fetched_at=fetched_at,
            raw_text=raw_text,
            confidence_score=parsed.confidence_score,
            created_at=self.clock.now(),
            parse_payload=parsed.extracted_fields,
        )
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO rule_review_queue (
                    review_id, source_url, fetched_at, raw_text, confidence_score, parse_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.review_id,
                    item.source_url,
                    item.fetched_at.isoformat(),
                    item.raw_text,
                    item.confidence_score,
                    self.repositories.storage.encode_json(item.parse_payload),
                    item.created_at.isoformat(),
                ),
            )
        return item

    def _refresh_deadlines_for_rule(self, conn, rule: RuleRecord, correlation_id: str, actor: str, actor_ip: str) -> None:
        rows = conn.execute("SELECT * FROM clients ORDER BY created_at").fetchall()
        for row in rows:
            client = self._client_from_row(dict(row))
            if self._rule_matches_client(rule, client):
                self._upsert_deadline_from_rule(conn, client, rule, correlation_id, actor, actor_ip)

    def _upsert_deadlines_for_client(self, conn, client: Client, correlation_id: str, actor: str, actor_ip: str) -> None:
        rows = conn.execute("SELECT * FROM rules WHERE status = ?", (RuleStatus.ACTIVE.value,)).fetchall()
        for row in rows:
            rule = self._rule_from_row(dict(row))
            if self._rule_matches_client(rule, client):
                self._upsert_deadline_from_rule(conn, client, rule, correlation_id, actor, actor_ip)

    def _upsert_deadline_from_rule(
        self,
        conn,
        client: Client,
        rule: RuleRecord,
        correlation_id: str,
        actor: str,
        actor_ip: str,
    ) -> None:
        existing = conn.execute(
            "SELECT * FROM deadlines WHERE client_id = ? AND tax_type = ? AND jurisdiction = ?",
            (client.client_id, rule.tax_type, rule.jurisdiction),
        ).fetchone()
        now = self.clock.now()
        if existing is None:
            deadline = Deadline(
                deadline_id=str(uuid4()),
                client_id=client.client_id,
                tenant_id=client.tenant_id,
                rule_id=rule.rule_id,
                tax_type=rule.tax_type,
                jurisdiction=rule.jurisdiction,
                due_date=rule.deadline_date,
                status=DeadlineStatus.PENDING,
                reminder_type=ReminderType.STANDARD,
                override_date=None,
                snoozed_until=None,
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                """
                INSERT INTO deadlines (
                    deadline_id, client_id, tenant_id, rule_id, tax_type, jurisdiction, due_date,
                    status, reminder_type, override_date, snoozed_until, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deadline.deadline_id,
                    deadline.client_id,
                    deadline.tenant_id,
                    deadline.rule_id,
                    deadline.tax_type,
                    deadline.jurisdiction,
                    deadline.due_date,
                    deadline.status.value,
                    deadline.reminder_type.value,
                    deadline.override_date,
                    deadline.snoozed_until,
                    deadline.created_at.isoformat(),
                    deadline.updated_at.isoformat(),
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=client.tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="deadline_created",
                object_type="deadline",
                object_id=deadline.deadline_id,
                before={},
                after={"rule_id": rule.rule_id, "due_date": deadline.due_date, "client_id": client.client_id},
                correlation_id=correlation_id,
            )
            self._rebuild_reminders(conn, deadline)
            self._publish(
                EventType.DEADLINE_UPDATED,
                {"tenant_id": client.tenant_id, "deadline_id": deadline.deadline_id, "due_date": deadline.due_date},
                actor,
            )
            return
        deadline = self._deadline_from_row(dict(existing))
        if deadline.override_date or deadline.due_date == rule.deadline_date:
            return
        conn.execute(
            "UPDATE deadlines SET rule_id = ?, due_date = ?, updated_at = ? WHERE deadline_id = ?",
            (rule.rule_id, rule.deadline_date, now.isoformat(), deadline.deadline_id),
        )
        self._insert_audit(
            conn=conn,
            tenant_id=client.tenant_id,
            actor=actor,
            actor_ip=actor_ip,
            action_type="deadline_updated",
            object_type="deadline",
            object_id=deadline.deadline_id,
            before={"due_date": deadline.due_date},
            after={"due_date": rule.deadline_date},
            correlation_id=correlation_id,
        )
        updated = Deadline(
            deadline_id=deadline.deadline_id,
            client_id=deadline.client_id,
            tenant_id=deadline.tenant_id,
            rule_id=deadline.rule_id,
            tax_type=deadline.tax_type,
            jurisdiction=deadline.jurisdiction,
            due_date=rule.deadline_date,
            status=deadline.status,
            reminder_type=deadline.reminder_type,
            override_date=deadline.override_date,
            snoozed_until=deadline.snoozed_until,
            created_at=deadline.created_at,
            updated_at=now,
        )
        self._rebuild_reminders(conn, updated)
        self._publish(
            EventType.DEADLINE_UPDATED,
            {"tenant_id": client.tenant_id, "deadline_id": deadline.deadline_id, "due_date": updated.due_date},
            actor,
        )

    def _insert_transition(
        self,
        conn,
        deadline: Deadline,
        new_status: DeadlineStatus,
        action: DeadlineAction,
        actor: str,
        metadata: dict,
        created_at: datetime,
    ) -> None:
        transition = DeadlineTransition(
            transition_id=str(uuid4()),
            deadline_id=deadline.deadline_id,
            tenant_id=deadline.tenant_id,
            previous_status=deadline.status.value,
            new_status=new_status.value,
            action=action.value,
            actor=actor,
            metadata=metadata,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO deadline_transitions (
                transition_id, deadline_id, tenant_id, previous_status, new_status, action, actor, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transition.transition_id,
                transition.deadline_id,
                transition.tenant_id,
                transition.previous_status,
                transition.new_status,
                transition.action,
                transition.actor,
                self.repositories.storage.encode_json(transition.metadata),
                transition.created_at.isoformat(),
            ),
        )

    def _rebuild_reminders(self, conn, deadline: Deadline) -> None:
        conn.execute(
            "UPDATE reminders SET status = ? WHERE deadline_id = ? AND status = ?",
            (ReminderStatus.CANCELLED.value, deadline.deadline_id, ReminderStatus.SCHEDULED.value),
        )
        if deadline.status in {DeadlineStatus.COMPLETED, DeadlineStatus.WAIVED}:
            return
        due_date = datetime.fromisoformat(f"{deadline.due_date}T09:00:00+00:00")
        for days in [30, 14, 7, 1]:
            self._insert_reminder(conn, deadline, due_date - timedelta(days=days), f"-{days}")
        if deadline.reminder_type is ReminderType.CRITICAL:
            for days in [3, 2, 1, 0]:
                self._insert_reminder(conn, deadline, due_date - timedelta(days=days), "repeat")

    def _insert_reminder(self, conn, deadline: Deadline, scheduled_at: datetime, reminder_day: str) -> None:
        conn.execute(
            """
            INSERT INTO reminders (
                reminder_id, deadline_id, tenant_id, client_id, scheduled_at, triggered_at,
                status, reminder_day, reminder_type, responded_at, response
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL)
            """,
            (
                str(uuid4()),
                deadline.deadline_id,
                deadline.tenant_id,
                deadline.client_id,
                scheduled_at.isoformat(),
                ReminderStatus.SCHEDULED.value,
                reminder_day,
                deadline.reminder_type.value,
            ),
        )

    def _insert_audit(
        self,
        *,
        conn,
        tenant_id: str,
        actor: str,
        actor_ip: str,
        action_type: str,
        object_type: str,
        object_id: str,
        before: dict,
        after: dict,
        correlation_id: str,
    ) -> None:
        if self.repositories.storage.fail_next_audit_write:
            self.repositories.storage.fail_next_audit_write = False
            raise RuntimeError("simulated audit write failure")
        record = AuditRecord(
            log_id=str(uuid4()),
            tenant_id=tenant_id,
            actor=actor,
            actor_ip=actor_ip,
            action_type=action_type,
            object_type=object_type,
            object_id=object_id,
            before=before,
            after=after,
            correlation_id=correlation_id,
            created_at=self.clock.now(),
        )
        conn.execute(
            """
            INSERT INTO audit_log (
                log_id, tenant_id, actor, actor_ip, action_type, object_type, object_id,
                before_json, after_json, correlation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.log_id,
                record.tenant_id,
                record.actor,
                record.actor_ip,
                record.action_type,
                record.object_type,
                record.object_id,
                self.repositories.storage.encode_json(record.before),
                self.repositories.storage.encode_json(record.after),
                record.correlation_id,
                record.created_at.isoformat(),
            ),
        )

    def _rule_matches_client(self, rule: RuleRecord, client: Client) -> bool:
        if client.entity_type not in rule.entity_types:
            return False
        return rule.jurisdiction == FEDERAL_JURISDICTION or rule.jurisdiction in client.registered_states

    def _client_from_row(self, row: dict) -> Client:
        return Client(
            client_id=row["client_id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            entity_type=row["entity_type"],
            registered_states=json.loads(row["registered_states"]),
            tax_year=row["tax_year"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _rule_from_row(self, row: dict) -> RuleRecord:
        return RuleRecord(
            rule_id=row["rule_id"],
            tax_type=row["tax_type"],
            jurisdiction=row["jurisdiction"],
            entity_types=json.loads(row["entity_types"]),
            deadline_date=row["deadline_date"],
            effective_from=row["effective_from"],
            source_url=row["source_url"],
            confidence_score=row["confidence_score"],
            status=RuleStatus(row["status"]),
            version=row["version"],
            created_at=self._parse_datetime(row["created_at"]),
            superseded_by=row["superseded_by"],
            raw_text=row["raw_text"],
            fetched_at=self._parse_datetime(row["fetched_at"]) if row["fetched_at"] else None,
        )

    def _review_from_row(self, row: dict) -> RuleReviewItem:
        return RuleReviewItem(
            review_id=row["review_id"],
            source_url=row["source_url"],
            fetched_at=self._parse_datetime(row["fetched_at"]),
            raw_text=row["raw_text"],
            confidence_score=row["confidence_score"],
            created_at=self._parse_datetime(row["created_at"]),
            parse_payload=json.loads(row["parse_payload"]),
        )

    def _deadline_from_row(self, row: dict) -> Deadline:
        return Deadline(
            deadline_id=row["deadline_id"],
            client_id=row["client_id"],
            tenant_id=row["tenant_id"],
            rule_id=row["rule_id"],
            tax_type=row["tax_type"],
            jurisdiction=row["jurisdiction"],
            due_date=row["due_date"],
            status=DeadlineStatus(row["status"]),
            reminder_type=ReminderType(row["reminder_type"]),
            override_date=row["override_date"],
            snoozed_until=self._parse_datetime(row["snoozed_until"]) if row["snoozed_until"] else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _reminder_from_row(self, row: dict) -> Reminder:
        return Reminder(
            reminder_id=row["reminder_id"],
            deadline_id=row["deadline_id"],
            tenant_id=row["tenant_id"],
            client_id=row["client_id"],
            scheduled_at=self._parse_datetime(row["scheduled_at"]),
            triggered_at=self._parse_datetime(row["triggered_at"]) if row["triggered_at"] else None,
            status=ReminderStatus(row["status"]),
            reminder_day=row["reminder_day"],
            reminder_type=ReminderType(row["reminder_type"]),
            responded_at=self._parse_datetime(row["responded_at"]) if row["responded_at"] else None,
            response=row["response"],
        )

    def _publish(self, event_type: EventType, payload: dict, source: str) -> None:
        self.event_bus.publish(
            Event(
                event_type=event_type,
                payload=payload,
                source=source,
                correlation_id=str(uuid4()),
                timestamp=self.clock.now(),
            )
        )

    def _parse_datetime(self, value: str) -> datetime:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
