from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from .ai_assist import AIAssistService
from .bus import InMemoryEventBus
from .clock import Clock
from .events import Event, EventType
from .models import (
    AuditRecord,
    Blocker,
    BlockerStatus,
    Client,
    ClientContact,
    ClientJurisdiction,
    ClientTaxProfile,
    Deadline,
    DeadlineAction,
    DeadlineStatus,
    DeadlineTransition,
    NoticeRecord,
    NoticeStatus,
    NotificationChannel,
    NotificationDelivery,
    NotificationRoute,
    NotificationStatus,
    Reminder,
    ReminderStatus,
    ReminderType,
    ProposedPlanItem,
    Task,
    TaskStatus,
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
GENERIC_BUSINESS_ENTITY_TYPES = ("c-corp", "s-corp", "llc", "partnership")
STATE_SPECIFIC_ENTITY_TYPES = {
    "pte_election": ("s-corp", "partnership", "llc"),
    "ptet": ("s-corp", "partnership", "llc"),
    "sales_tax": GENERIC_BUSINESS_ENTITY_TYPES,
    "franchise_tax": GENERIC_BUSINESS_ENTITY_TYPES,
    "state_income": GENERIC_BUSINESS_ENTITY_TYPES,
}
IMPORT_FIELD_SPECS = (
    {
        "key": "client_name",
        "target_field": "Client name",
        "required": True,
        "aliases": ("client name", "client", "account name", "company name", "name"),
    },
    {
        "key": "entity_type",
        "target_field": "Entity type",
        "required": True,
        "aliases": ("entity type", "entity / return type", "return type", "entity", "business type"),
    },
    {
        "key": "operating_states",
        "target_field": "Operating states",
        "required": True,
        "aliases": ("operating states", "state footprint", "states", "registered states", "state"),
    },
    {
        "key": "home_jurisdiction",
        "target_field": "Home jurisdiction",
        "required": False,
        "aliases": ("home jurisdiction", "resident state", "home state", "domicile state"),
    },
    {
        "key": "payroll_states",
        "target_field": "Payroll states",
        "required": False,
        "aliases": ("payroll states", "payroll state", "payroll footprint"),
    },
    {
        "key": "responsible_cpa",
        "target_field": "Responsible CPA",
        "required": False,
        "aliases": ("responsible cpa", "owner", "manager", "account owner"),
    },
)


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

    def get_tenant(self, tenant_id: str) -> Tenant:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tenants WHERE tenant_id = ? AND is_deleted = 0",
                (tenant_id,),
            ).fetchone()
        if row is None:
            raise KeyError(tenant_id)
        return Tenant(
            tenant_id=row["tenant_id"],
            name=row["name"],
            created_at=self._parse_datetime(row["created_at"]),
            is_deleted=bool(row["is_deleted"]),
            deleted_at=self._parse_datetime(row["deleted_at"]) if row["deleted_at"] else None,
        )

    def register_client(
        self,
        tenant_id: str,
        name: str,
        entity_type: str,
        registered_states: list[str],
        tax_year: int,
        client_type: str = "business",
        legal_name: str | None = None,
        home_jurisdiction: str | None = None,
        primary_contact_name: str | None = None,
        primary_contact_email: str | None = None,
        primary_contact_phone: str | None = None,
        preferred_communication_channel: str | None = None,
        responsible_cpa: str | None = None,
        entity_election: str | None = None,
        first_year_filing: bool | None = None,
        final_year_filing: bool | None = None,
        extension_requested: bool | None = None,
        extension_filed: bool | None = None,
        estimated_tax_required: bool | None = None,
        payroll_present: bool | None = None,
        contractor_reporting_required: bool | None = None,
        notice_received: bool | None = None,
        intake_status: str = "draft",
        profile_source: str = "manual",
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Client:
        now = self.clock.now()
        normalized_states = sorted({state.upper() for state in registered_states})
        normalized_home_jurisdiction = home_jurisdiction.upper() if home_jurisdiction else None
        client = Client(
            client_id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            entity_type=entity_type.lower(),
            registered_states=normalized_states,
            tax_year=tax_year,
            created_at=now,
            updated_at=now,
            client_type=client_type.lower(),
            legal_name=legal_name,
            home_jurisdiction=normalized_home_jurisdiction,
            primary_contact_name=primary_contact_name,
            primary_contact_email=primary_contact_email,
            primary_contact_phone=primary_contact_phone,
            preferred_communication_channel=preferred_communication_channel,
            responsible_cpa=responsible_cpa,
        )
        tax_profile = ClientTaxProfile(
            profile_id=str(uuid4()),
            tenant_id=tenant_id,
            client_id=client.client_id,
            tax_year=tax_year,
            entity_election=entity_election,
            first_year_filing=first_year_filing,
            final_year_filing=final_year_filing,
            extension_requested=extension_requested,
            extension_filed=extension_filed,
            estimated_tax_required=estimated_tax_required,
            payroll_present=payroll_present,
            contractor_reporting_required=contractor_reporting_required,
            notice_received=notice_received,
            intake_status=intake_status,
            source=profile_source,
            created_at=now,
            updated_at=now,
        )
        primary_contact = None
        if primary_contact_name or primary_contact_email or primary_contact_phone:
            primary_contact = ClientContact(
                contact_id=str(uuid4()),
                tenant_id=tenant_id,
                client_id=client.client_id,
                name=primary_contact_name or name,
                role="primary",
                email=primary_contact_email,
                phone=primary_contact_phone,
                preferred_channel=preferred_communication_channel,
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO clients (
                    client_id, tenant_id, name, entity_type, registered_states, tax_year,
                    client_type, legal_name, home_jurisdiction, primary_contact_name,
                    primary_contact_email, primary_contact_phone, preferred_communication_channel,
                    responsible_cpa, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client.client_id,
                    client.tenant_id,
                    client.name,
                    client.entity_type,
                    self.repositories.storage.encode_json(client.registered_states),
                    client.tax_year,
                    client.client_type,
                    client.legal_name,
                    client.home_jurisdiction,
                    client.primary_contact_name,
                    client.primary_contact_email,
                    client.primary_contact_phone,
                    client.preferred_communication_channel,
                    client.responsible_cpa,
                    self._bool_to_db(client.is_active),
                    client.created_at.isoformat(),
                    client.updated_at.isoformat(),
                ),
            )
            self._upsert_client_tax_profile(conn, tax_profile)
            self._sync_client_jurisdictions(
                conn,
                tenant_id=tenant_id,
                client_id=client.client_id,
                tax_year=client.tax_year,
                registered_states=client.registered_states,
                home_jurisdiction=client.home_jurisdiction,
                source=profile_source,
            )
            self._upsert_primary_client_contact(conn, primary_contact)
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
                    "client_type": client.client_type,
                    "legal_name": client.legal_name,
                    "home_jurisdiction": client.home_jurisdiction,
                    "primary_contact_name": client.primary_contact_name,
                    "primary_contact_email": client.primary_contact_email,
                    "primary_contact_phone": client.primary_contact_phone,
                    "preferred_communication_channel": client.preferred_communication_channel,
                    "responsible_cpa": client.responsible_cpa,
                    "intake_status": tax_profile.intake_status,
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
            self._sync_client_jurisdictions(
                conn,
                tenant_id=tenant_id,
                client_id=client_id,
                tax_year=client.tax_year,
                registered_states=normalized_states,
                home_jurisdiction=client.home_jurisdiction,
                source="manual",
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
                before={"registered_states": self._decode_json_field(row["registered_states"], default=[])},
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

    def _extract_dates_from_text(self, raw_text: str) -> list[str]:
        patterns = [
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
        ]
        matches: list[str] = []
        for pattern in patterns:
            matches.extend(re.findall(pattern, raw_text, flags=re.IGNORECASE))
        return matches

    def _normalize_date_string(self, value: str | None) -> str | None:
        if not value:
            return None
        candidate = value.strip()
        for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def _state_specific_parse_hints(
        self,
        *,
        raw_text: str,
        source_key: str | None,
        source_url: str,
        fetched_at: datetime | None,
    ) -> str:
        if re.search(r"\btax[_ ]type\s*:", raw_text, re.IGNORECASE):
            return raw_text

        normalized = " ".join(raw_text.split())
        lowered = normalized.lower()
        jurisdiction = None
        if source_key and source_key.startswith("state_"):
            jurisdiction = source_key.removeprefix("state_").upper()
        elif "ftb.ca.gov" in source_url:
            jurisdiction = "CA"
        elif "comptroller.texas.gov" in source_url:
            jurisdiction = "TX"
        elif "tax.ny.gov" in source_url:
            jurisdiction = "NY"

        tax_type = None
        if jurisdiction == "CA":
            if "pte election" in lowered or "pass-through entity elective tax" in lowered:
                tax_type = "pte_election"
            elif "franchise tax" in lowered:
                tax_type = "franchise_tax"
            elif "sales tax" in lowered:
                tax_type = "sales_tax"
        elif jurisdiction == "TX":
            if "economic nexus" in lowered or "remote-seller" in lowered or "remote seller" in lowered or "sales tax" in lowered:
                tax_type = "sales_tax"
            elif "franchise tax" in lowered or "margin tax" in lowered:
                tax_type = "franchise_tax"
        elif jurisdiction == "NY":
            if "pass-through entity tax" in lowered or re.search(r"\bptet\b", lowered):
                tax_type = "ptet"
            elif "sales tax" in lowered:
                tax_type = "sales_tax"
            elif "franchise tax" in lowered or "corporation tax" in lowered:
                tax_type = "franchise_tax"

        if not jurisdiction and not tax_type:
            return raw_text

        dates = [value for value in (self._normalize_date_string(token) for token in self._extract_dates_from_text(normalized)) if value]
        deadline_date = dates[-1] if dates else None
        effective_from = dates[0] if dates else (fetched_at.date().isoformat() if fetched_at else None)
        entity_types = STATE_SPECIFIC_ENTITY_TYPES.get(tax_type or "", GENERIC_BUSINESS_ENTITY_TYPES)
        structured_lines = [
            normalized,
            f"jurisdiction: {jurisdiction}" if jurisdiction else None,
            f"tax_type: {tax_type}" if tax_type else None,
            f"entity_types: {', '.join(entity_types)}" if entity_types else None,
            f"deadline_date: {deadline_date}" if deadline_date else None,
            f"effective_from: {effective_from}" if effective_from else None,
        ]
        return "\n".join(line for line in structured_lines if line)

    def parse_rule_text(
        self,
        raw_text: str,
        *,
        source_key: str | None = None,
        source_url: str = "",
        fetched_at: datetime | None = None,
    ) -> RuleParseResult:
        raw_text = self._state_specific_parse_hints(
            raw_text=raw_text,
            source_key=source_key,
            source_url=source_url,
            fetched_at=fetched_at,
        )

        def extract(label: str) -> str | None:
            match = re.search(rf"{label}\s*:\s*(.+)", raw_text, re.IGNORECASE)
            return match.group(1).strip() if match else None

        tax_type = extract("tax[_ ]type")
        jurisdiction = extract("jurisdiction")
        entity_types_raw = extract("entity[_ ]types")
        deadline_date = self._normalize_date_string(extract("deadline[_ ]date"))
        effective_from = self._normalize_date_string(extract("effective[_ ]from"))
        entity_types = [part.strip().lower() for part in entity_types_raw.split(",")] if entity_types_raw else []
        confidence = 0.25 + sum(bool(value) for value in [tax_type, jurisdiction, entity_types, deadline_date, effective_from]) * 0.15
        if re.search(r"\b(irs|ftb|tax|deadline|due date)\b", raw_text, re.IGNORECASE):
            confidence += 0.1
        if source_key in {"state_ca", "state_tx", "state_ny"} and tax_type and jurisdiction:
            confidence += 0.05
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
        source_key: str | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> RuleRecord | RuleReviewItem:
        parsed = self.parse_rule_text(
            raw_text,
            source_key=source_key,
            source_url=source_url,
            fetched_at=fetched_at,
        )
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
            source_key=source_definition.source_key,
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
        self._publish(
            EventType.RULE_CHANGED,
            {"rule_id": rule.rule_id, "jurisdiction": rule.jurisdiction, "deadline_date": rule.deadline_date},
            actor,
        )
        self._refresh_deadlines_for_rule(rule, correlation_id, actor, actor_ip)
        return rule

    def list_rules(self) -> list[RuleRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM rules ORDER BY created_at DESC").fetchall()
        return [self._rule_from_row(dict(row)) for row in rows]

    def list_deadlines(
        self,
        tenant_id: str,
        client_id: str | None = None,
        *,
        within_days: int | None = None,
        status: DeadlineStatus | None = None,
        jurisdiction: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Deadline]:
        query = "SELECT * FROM deadlines WHERE tenant_id = ?"
        params: list[object] = [tenant_id]
        if client_id:
            query += " AND client_id = ?"
            params.append(client_id)
        if within_days is not None:
            today = self.clock.now().date().isoformat()
            cutoff = (self.clock.now().date() + timedelta(days=within_days)).isoformat()
            query += " AND due_date >= ? AND due_date <= ?"
            params.extend([today, cutoff])
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if jurisdiction:
            query += " AND jurisdiction = ?"
            params.append(jurisdiction.upper())
        query += " ORDER BY due_date, created_at"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
            if offset:
                query += " OFFSET ?"
                params.append(offset)
        elif offset:
            query += " LIMIT -1 OFFSET ?"
            params.append(offset)
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

    def available_deadline_actions(self, tenant_id: str, deadline_id: str) -> dict[str, object]:
        deadline = self.get_deadline(tenant_id, deadline_id)
        actions = [action.value for action in self.state_machine.available_actions(deadline.status) if action is not DeadlineAction.RESUME]
        return {
            "deadline_id": deadline.deadline_id,
            "current_status": deadline.status.value,
            "available_actions": actions,
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

    def configure_notification_route(
        self,
        tenant_id: str,
        channel: NotificationChannel,
        destination: str,
        *,
        enabled: bool = True,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> NotificationRoute:
        route = NotificationRoute(
            route_id=str(uuid4()),
            tenant_id=tenant_id,
            channel=channel,
            destination=destination,
            enabled=enabled,
            created_at=self.clock.now(),
        )
        with self._transaction(tenant_id=tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO notification_routes (
                    route_id, tenant_id, channel, destination, enabled, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    route.route_id,
                    route.tenant_id,
                    route.channel.value,
                    route.destination,
                    1 if route.enabled else 0,
                    route.created_at.isoformat(),
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="notification_route_created",
                object_type="notification_route",
                object_id=route.route_id,
                before={},
                after={"channel": route.channel.value, "destination": route.destination, "enabled": route.enabled},
                correlation_id=str(uuid4()),
            )
        return route

    def list_notification_routes(self, tenant_id: str) -> list[NotificationRoute]:
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(
                "SELECT * FROM notification_routes WHERE tenant_id = ? ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [self._notification_route_from_row(dict(row)) for row in rows]

    def update_notification_route(
        self,
        tenant_id: str,
        route_id: str,
        *,
        destination: str | None = None,
        enabled: bool | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> NotificationRoute:
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM notification_routes WHERE tenant_id = ? AND route_id = ?",
                (tenant_id, route_id),
            ).fetchone()
            if row is None:
                raise KeyError(route_id)
            existing = self._notification_route_from_row(dict(row))
            updated = NotificationRoute(
                route_id=existing.route_id,
                tenant_id=existing.tenant_id,
                channel=existing.channel,
                destination=destination if destination is not None else existing.destination,
                enabled=enabled if enabled is not None else existing.enabled,
                created_at=existing.created_at,
            )
            conn.execute(
                """
                UPDATE notification_routes
                SET destination = ?, enabled = ?
                WHERE tenant_id = ? AND route_id = ?
                """,
                (
                    updated.destination,
                    1 if updated.enabled else 0,
                    tenant_id,
                    route_id,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="notification_route_updated",
                object_type="notification_route",
                object_id=route_id,
                before=self._audit_payload(existing),
                after=self._audit_payload(updated),
                correlation_id=correlation_id,
            )
        return updated

    def settings_payload(self, tenant_id: str) -> dict[str, object]:
        tenant = self.get_tenant(tenant_id)
        routes = self.list_notification_routes(tenant_id)
        pending_deliveries = self.list_notification_deliveries(tenant_id, pending_only=True)
        return {
            "tenant": {
                "tenant_id": tenant.tenant_id,
                "name": tenant.name,
                "created_at": tenant.created_at.isoformat(),
            },
            "notification_routes": [
                {
                    "route_id": route.route_id,
                    "channel": route.channel.value,
                    "destination": route.destination,
                    "enabled": route.enabled,
                    "created_at": route.created_at.isoformat(),
                }
                for route in routes
            ],
            "notification_summary": {
                "enabled_channels": len([route for route in routes if route.enabled]),
                "pending_deliveries": len(pending_deliveries),
            },
        }

    def list_notification_deliveries(
        self,
        tenant_id: str,
        deadline_id: str | None = None,
        *,
        pending_only: bool = False,
    ) -> list[NotificationDelivery]:
        query = "SELECT * FROM notification_deliveries WHERE tenant_id = ?"
        params: list[object] = [tenant_id]
        if deadline_id:
            query += " AND deadline_id = ?"
            params.append(deadline_id)
        if pending_only:
            query += " AND status = ?"
            params.append(NotificationStatus.PENDING.value)
        query += " ORDER BY created_at"
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._notification_delivery_from_row(dict(row)) for row in rows]

    def trigger_due_reminders(self, now: datetime | None = None, tenant_id: str | None = None) -> int:
        now = now or self.clock.now()
        query = "SELECT * FROM reminders WHERE status = ? AND scheduled_at <= ?"
        params: list[object] = [ReminderStatus.SCHEDULED.value, now.isoformat()]
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        query += " ORDER BY scheduled_at"
        with self._transaction(tenant_id=tenant_id) as conn:
            rows = conn.execute(
                query,
                params,
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
                self._queue_notification_deliveries(
                    conn=conn,
                    reminder=self._reminder_from_row(dict({**dict(row), "status": ReminderStatus.TRIGGERED.value, "triggered_at": now.isoformat()})),
                    actor="scheduler",
                    actor_ip="127.0.0.1",
                )
        return len(rows)

    def dispatch_notification_deliveries(
        self,
        tenant_id: str,
        notifier_registry,
        *,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> int:
        deliveries = self.list_notification_deliveries(tenant_id, pending_only=True)
        sent = 0
        for delivery in deliveries:
            notifier = notifier_registry.get(delivery.channel)
            status = NotificationStatus.SENT
            provider_message_id = None
            error_message = None
            sent_at = self.clock.now()
            try:
                provider_message_id = notifier.send(delivery)
            except Exception as exc:
                status = NotificationStatus.FAILED
                error_message = str(exc)
                sent_at = None
            with self._transaction(tenant_id=tenant_id) as conn:
                conn.execute(
                    """
                    UPDATE notification_deliveries
                    SET status = ?, provider_message_id = ?, error_message = ?, sent_at = ?
                    WHERE delivery_id = ?
                    """,
                    (
                        status.value,
                        provider_message_id,
                        error_message,
                        sent_at.isoformat() if sent_at else None,
                        delivery.delivery_id,
                    ),
                )
                self._insert_audit(
                    conn=conn,
                    tenant_id=tenant_id,
                    actor=actor,
                    actor_ip=actor_ip,
                    action_type="notification_delivery_updated",
                    object_type="notification_delivery",
                    object_id=delivery.delivery_id,
                    before={"status": NotificationStatus.PENDING.value},
                    after={"status": status.value, "channel": delivery.channel.value},
                    correlation_id=str(uuid4()),
                )
            if status is NotificationStatus.SENT:
                sent += 1
        return sent

    def draft_client_email(
        self,
        tenant_id: str,
        client_id: str,
        *,
        deadline_id: str | None = None,
        task_id: str | None = None,
        extra_context: str | None = None,
    ) -> dict[str, object]:
        task = self.get_task(tenant_id, task_id) if task_id else None
        if task and deadline_id is None and task.source_type in {"deadline", "import_plan"}:
            deadline_id = task.source_id
        client = self.get_client(tenant_id, client_id)
        deadline = self._email_target_deadline(tenant_id, client_id, deadline_id)
        context = {
            "tenant_id": tenant_id,
            "client_id": client.client_id,
            "client_name": client.name,
            "contact_name": client.primary_contact_name,
            "contact_email": self._client_email_destination(tenant_id, client),
            "deadline_id": deadline.deadline_id,
            "tax_type": deadline.tax_type,
            "jurisdiction": deadline.jurisdiction,
            "due_date": deadline.due_date,
            "status": deadline.status.value,
            "task_title": task.title if task else None,
            "task_description": task.description if task else None,
            "blocker_reason": self._open_blocker_reason_for_client(tenant_id, client_id),
            "extra_context": extra_context,
        }
        draft = AIAssistService().draft_client_email(context)
        draft["to"] = context["contact_email"]
        draft["deadline_id"] = deadline.deadline_id
        draft["task_id"] = task.task_id if task else None
        return draft

    def queue_client_email(
        self,
        tenant_id: str,
        client_id: str,
        *,
        subject: str,
        body: str,
        deadline_id: str | None = None,
        task_id: str | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> NotificationDelivery:
        if task_id:
            task = self.get_task(tenant_id, task_id)
            if task.client_id != client_id:
                raise ValueError("task does not belong to client")
            if deadline_id is None and task.source_type in {"deadline", "import_plan"}:
                deadline_id = task.source_id
        if not deadline_id:
            raise ValueError("client email must be anchored to a work item deadline")
        client = self.get_client(tenant_id, client_id)
        destination = self._client_email_destination(tenant_id, client)
        if not destination:
            raise ValueError(f"client {client.name} has no email contact")
        deadline = self._email_target_deadline(tenant_id, client_id, deadline_id)
        now = self.clock.now()
        reminder = Reminder(
            reminder_id=str(uuid4()),
            deadline_id=deadline.deadline_id,
            tenant_id=tenant_id,
            client_id=client_id,
            scheduled_at=now,
            triggered_at=now,
            status=ReminderStatus.TRIGGERED,
            reminder_day="manual-email",
            reminder_type=deadline.reminder_type,
            responded_at=None,
            response=None,
        )
        delivery = NotificationDelivery(
            delivery_id=str(uuid4()),
            tenant_id=tenant_id,
            client_id=client_id,
            deadline_id=deadline.deadline_id,
            reminder_id=reminder.reminder_id,
            channel=NotificationChannel.EMAIL,
            destination=destination,
            subject=subject,
            body=body,
            status=NotificationStatus.PENDING,
            provider_message_id=None,
            error_message=None,
            created_at=now,
            sent_at=None,
        )
        with self._transaction(tenant_id=tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO reminders (
                    reminder_id, deadline_id, tenant_id, client_id, scheduled_at, triggered_at,
                    status, reminder_day, reminder_type, responded_at, response
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    reminder.reminder_id,
                    reminder.deadline_id,
                    reminder.tenant_id,
                    reminder.client_id,
                    reminder.scheduled_at.isoformat(),
                    reminder.triggered_at.isoformat() if reminder.triggered_at else None,
                    reminder.status.value,
                    reminder.reminder_day,
                    reminder.reminder_type.value,
                ),
            )
            conn.execute(
                """
                INSERT INTO notification_deliveries (
                    delivery_id, tenant_id, client_id, deadline_id, reminder_id, channel, destination,
                    subject, body, status, provider_message_id, error_message, created_at, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL)
                """,
                (
                    delivery.delivery_id,
                    delivery.tenant_id,
                    delivery.client_id,
                    delivery.deadline_id,
                    delivery.reminder_id,
                    delivery.channel.value,
                    delivery.destination,
                    delivery.subject,
                    delivery.body,
                    delivery.status.value,
                    delivery.created_at.isoformat(),
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="client_email_queued",
                object_type="notification_delivery",
                object_id=delivery.delivery_id,
                before={},
                after={
                    "client_id": client_id,
                    "deadline_id": deadline.deadline_id,
                    "destination": destination,
                    "subject": subject,
                },
                correlation_id=str(uuid4()),
            )
        return delivery

    def export_deadlines(
        self,
        tenant_id: str,
        actor: str,
        actor_ip: str = "127.0.0.1",
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        deadlines = self.list_deadlines(tenant_id, client_id=client_id)
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
                object_id=client_id or tenant_id,
                before={},
                after={"count": len(payload), "client_id": client_id},
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
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute("SELECT * FROM clients WHERE tenant_id = ? ORDER BY created_at", (tenant_id,)).fetchall()
        return [self._client_from_row(dict(row)) for row in rows]

    def get_client(self, tenant_id: str, client_id: str) -> Client:
        with self._connect(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM clients WHERE tenant_id = ? AND client_id = ?",
                (tenant_id, client_id),
            ).fetchone()
        if row is None:
            raise KeyError(client_id)
        return self._client_from_row(dict(row))

    def preview_import_csv(self, csv_path: str | Path) -> dict[str, object]:
        path = Path(csv_path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            return {
                "source_name": path.name,
                "source_kind": "CSV import",
                "imported_rows": 0,
                "summary": "The file is empty, so there is nothing to map yet.",
                "mappings": [],
                "missing_fields": ["Add at least one client row before continuing."],
                "extra_columns": [],
                "sample_rows": [],
                "ready_to_generate": False,
                "required_mappings": 0,
                "resolved_required_mappings": 0,
            }
        headers = rows[0]
        data_rows = [self._normalize_import_row(headers, row) for row in rows[1:]]
        return self.preview_import_table(
            source_name=path.name,
            source_kind="CSV import",
            headers=headers,
            rows=data_rows,
        )

    def preview_import_text(
        self,
        *,
        source_name: str,
        csv_text: str,
        source_kind: str = "CSV import",
        mapping_overrides: dict[str, str] | None = None,
    ) -> dict[str, object]:
        reader = csv.reader(StringIO(csv_text))
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            return self.preview_import_table(source_name=source_name, source_kind=source_kind, headers=[], rows=[])
        headers = rows[0]
        data_rows = [self._normalize_import_row(headers, row) for row in rows[1:]]
        return self.preview_import_table(
            source_name=source_name,
            source_kind=source_kind,
            headers=headers,
            rows=data_rows,
            mapping_overrides=mapping_overrides,
        )

    def preview_import_table(
        self,
        *,
        source_name: str,
        source_kind: str,
        headers: list[str],
        rows: list[list[str]],
        mapping_overrides: dict[str, str] | None = None,
    ) -> dict[str, object]:
        mappings, matched_targets, extra_columns = self._analyze_import_headers(headers)
        if mapping_overrides:
            mappings, matched_targets, extra_columns = self._apply_import_mapping_overrides(
                headers,
                mappings=mappings,
                matched_targets=matched_targets,
                mapping_overrides=mapping_overrides,
            )
        missing_fields = self._build_import_missing_fields(rows, matched_targets)
        required_mappings = sum(1 for spec in IMPORT_FIELD_SPECS if spec["required"])
        resolved_required_mappings = sum(
            1 for spec in IMPORT_FIELD_SPECS if spec["required"] and spec["key"] in matched_targets
        )
        ready_to_generate = resolved_required_mappings == required_mappings and not missing_fields
        summary = self._build_import_summary(
            imported_rows=len(rows),
            resolved_required_mappings=resolved_required_mappings,
            required_mappings=required_mappings,
            missing_count=len(missing_fields),
        )
        return {
            "source_name": source_name,
            "source_kind": source_kind,
            "imported_rows": len(rows),
            "summary": summary,
            "mappings": mappings,
            "missing_fields": missing_fields,
            "extra_columns": extra_columns,
            "sample_rows": rows[:3],
            "ready_to_generate": ready_to_generate,
            "required_mappings": required_mappings,
            "resolved_required_mappings": resolved_required_mappings,
            "ai_assist": self._build_import_ai_assist(
                headers=headers,
                rows=rows,
                mappings=mappings,
                matched_targets=matched_targets,
                missing_fields=missing_fields,
            ),
        }

    def apply_import_csv(
        self,
        tenant_id: str,
        csv_path: str | Path,
        *,
        tax_year: int,
        default_client_type: str = "business",
        create_initial_tasks: bool = True,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> dict[str, object]:
        path = Path(csv_path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            return {
                "source_name": path.name,
                "created_clients": [],
                "created_blockers": [],
                "created_tasks": [],
                "skipped_rows": [],
                "dashboard": self.dashboard_payload(tenant_id),
            }
        headers = rows[0]
        data_rows = [self._normalize_import_row(headers, row) for row in rows[1:]]
        _mappings, matched_targets, _extra_columns = self._analyze_import_headers(headers)
        missing_required_targets = [spec["target_field"] for spec in IMPORT_FIELD_SPECS if spec["required"] and spec["key"] not in matched_targets]
        if missing_required_targets:
            raise ValueError(f"import apply requires mapped columns for: {', '.join(missing_required_targets)}")

        contact_name_index = self._match_optional_import_column(
            headers,
            ("primary contact", "contact name", "client contact", "owner name"),
        )
        contact_email_index = self._match_optional_import_column(
            headers,
            ("contact email", "primary email", "email", "client email"),
        )
        contact_phone_index = self._match_optional_import_column(
            headers,
            ("contact phone", "phone", "primary phone", "client phone"),
        )
        responsible_cpa_index = matched_targets.get("responsible_cpa")

        created_clients: list[Client] = []
        created_blockers: list[Blocker] = []
        created_tasks: list[Task] = []
        skipped_rows: list[dict[str, object]] = []
        for row_index, row in enumerate(data_rows):
            client_name = self._extract_import_value(row, matched_targets.get("client_name"))
            entity_type = self._extract_import_value(row, matched_targets.get("entity_type"))
            operating_states_raw = self._extract_import_value(row, matched_targets.get("operating_states"))
            home_jurisdiction = self._extract_import_value(row, matched_targets.get("home_jurisdiction"))
            payroll_states_raw = self._extract_import_value(row, matched_targets.get("payroll_states"))
            contact_name = self._extract_import_value(row, contact_name_index)
            contact_email = self._extract_import_value(row, contact_email_index)
            contact_phone = self._extract_import_value(row, contact_phone_index)
            responsible_cpa = self._extract_import_value(row, responsible_cpa_index)

            if not client_name or not entity_type or not operating_states_raw:
                skipped_rows.append(
                    {
                        "row_number": row_index + 2,
                        "client_name": client_name or None,
                        "reason": "Missing a required client value after mapping.",
                    }
                )
                continue

            registered_states = self._split_import_states(operating_states_raw)
            if not registered_states:
                skipped_rows.append(
                    {
                        "row_number": row_index + 2,
                        "client_name": client_name,
                        "reason": "Could not derive any operating states from the mapped state column.",
                    }
                )
                continue

            client = self.register_client(
                tenant_id=tenant_id,
                name=client_name,
                entity_type=self._normalize_import_entity_type(entity_type),
                registered_states=registered_states,
                tax_year=tax_year,
                client_type=self._infer_client_type(entity_type, default_client_type),
                legal_name=client_name,
                home_jurisdiction=home_jurisdiction or None,
                primary_contact_name=contact_name or None,
                primary_contact_email=contact_email or None,
                primary_contact_phone=contact_phone or None,
                responsible_cpa=responsible_cpa or None,
                intake_status="needs_followup" if not home_jurisdiction else "ready",
                profile_source="import",
                payroll_present=bool(payroll_states_raw.strip()) if payroll_states_raw else None,
                actor=actor,
                actor_ip=actor_ip,
            )
            created_clients.append(client)

            row_blockers = self._generate_import_blockers_for_client(
                client=client,
                row=row,
                row_number=row_index + 2,
                matched_targets=matched_targets,
                actor=actor,
                actor_ip=actor_ip,
            )
            created_blockers.extend(row_blockers)

            if create_initial_tasks:
                row_tasks = self._generate_import_tasks_for_client(
                    client=client,
                    actor=actor,
                    actor_ip=actor_ip,
                )
                created_tasks.extend(row_tasks)

        proposed_plan = self._build_import_plan_for_clients(tenant_id=tenant_id, clients=created_clients)

        return {
            "source_name": path.name,
            "created_clients": created_clients,
            "created_blockers": created_blockers,
            "created_tasks": created_tasks,
            "proposed_plan": proposed_plan,
            "initial_task_creation_deferred": not create_initial_tasks,
            "skipped_rows": skipped_rows,
            "dashboard": self.dashboard_payload(tenant_id),
        }

    def approve_import_plan(
        self,
        tenant_id: str,
        proposed_plan: list[dict[str, object]] | list[ProposedPlanItem],
        *,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> dict[str, object]:
        created_tasks: list[Task] = []
        skipped_items: list[dict[str, object]] = []
        summary = {"now": 0, "later": 0, "skip": 0}

        for raw_item in proposed_plan:
            item = raw_item if isinstance(raw_item, ProposedPlanItem) else self._coerce_proposed_plan_item(raw_item)
            decision = str((raw_item.get("decision") if isinstance(raw_item, dict) else None) or item.default_action).strip().lower()
            planned_window = str((raw_item.get("planned_window") if isinstance(raw_item, dict) else None) or item.recommended_window).strip().lower()

            if decision not in {"now", "later", "skip"}:
                raise ValueError(f"unsupported plan decision: {decision}")
            summary[decision] += 1
            if decision == "skip":
                skipped_items.append(
                    {
                        "plan_item_id": item.plan_item_id,
                        "client_id": item.client_id,
                        "client_name": item.client_name,
                        "task_title": item.task_title,
                        "reason": "Skipped during plan review.",
                    }
                )
                continue

            existing = self._find_open_task_for_source(
                tenant_id,
                item.client_id,
                "import_plan",
                item.deadline_id,
            )
            if existing is not None:
                skipped_items.append(
                    {
                        "plan_item_id": item.plan_item_id,
                        "client_id": item.client_id,
                        "client_name": item.client_name,
                        "task_title": item.task_title,
                        "reason": "An open plan task already exists for this deadline.",
                    }
                )
                continue

            due_at = self._planned_due_at_for_window(planned_window, related_due_date=item.related_due_date)
            created_tasks.append(
                self.create_task(
                    tenant_id=tenant_id,
                    client_id=item.client_id,
                    title=item.task_title,
                    description=(
                        f"Approved from import plan review. Related filing due {item.related_due_date}. "
                        f"Reason: {item.reason}"
                    ),
                    task_type="import_plan",
                    priority="high" if item.urgency == "urgent" else "normal" if item.urgency == "medium" else "low",
                    source_type="import_plan",
                    source_id=item.deadline_id,
                    due_at=due_at,
                    actor=actor,
                    actor_ip=actor_ip,
                )
            )

        return {
            "summary": summary,
            "created_tasks": created_tasks,
            "skipped_items": skipped_items,
            "dashboard": self.dashboard_payload(tenant_id),
        }

    def get_client_bundle(self, tenant_id: str, client_id: str) -> dict[str, object]:
        with self._connect(tenant_id=tenant_id) as conn:
            client_row = conn.execute(
                "SELECT * FROM clients WHERE tenant_id = ? AND client_id = ?",
                (tenant_id, client_id),
            ).fetchone()
            if client_row is None:
                raise KeyError(client_id)
            profile_rows = conn.execute(
                """
                SELECT * FROM client_tax_profiles
                WHERE tenant_id = ? AND client_id = ?
                ORDER BY tax_year DESC, created_at DESC
                """,
                (tenant_id, client_id),
            ).fetchall()
            jurisdiction_rows = conn.execute(
                """
                SELECT * FROM client_jurisdictions
                WHERE tenant_id = ? AND client_id = ?
                ORDER BY tax_year DESC, jurisdiction_type, jurisdiction
                """,
                (tenant_id, client_id),
            ).fetchall()
            contact_rows = conn.execute(
                """
                SELECT * FROM client_contacts
                WHERE tenant_id = ? AND client_id = ?
                ORDER BY is_primary DESC, created_at
                """,
                (tenant_id, client_id),
            ).fetchall()
            task_rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE tenant_id = ? AND client_id = ?
                ORDER BY created_at DESC
                """,
                (tenant_id, client_id),
            ).fetchall()
            blocker_rows = conn.execute(
                """
                SELECT * FROM blockers
                WHERE tenant_id = ? AND client_id = ?
                ORDER BY created_at DESC
                """,
                (tenant_id, client_id),
            ).fetchall()

        return {
            "client": self.get_client(tenant_id, client_id),
            "tax_profiles": [self._client_tax_profile_from_row(dict(row)) for row in profile_rows],
            "jurisdictions": [self._client_jurisdiction_from_row(dict(row)) for row in jurisdiction_rows],
            "contacts": [self._client_contact_from_row(dict(row)) for row in contact_rows],
            "tasks": [self._task_from_row(dict(row)) for row in task_rows],
            "blockers": [self._blocker_from_row(dict(row)) for row in blocker_rows],
            "deadlines": self.list_deadlines(tenant_id, client_id),
        }

    def create_task(
        self,
        tenant_id: str,
        client_id: str,
        *,
        title: str,
        description: str | None = None,
        task_type: str = "manual",
        priority: str = "normal",
        source_type: str = "manual",
        source_id: str | None = None,
        owner_user_id: str | None = None,
        due_at: datetime | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Task:
        now = self.clock.now()
        task = Task(
            task_id=str(uuid4()),
            tenant_id=tenant_id,
            client_id=client_id,
            title=title,
            description=description,
            task_type=task_type,
            status=TaskStatus.OPEN,
            priority=priority,
            source_type=source_type,
            source_id=source_id,
            owner_user_id=owner_user_id,
            due_at=due_at,
            created_at=now,
            updated_at=now,
        )
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            client_row = conn.execute(
                "SELECT client_id FROM clients WHERE tenant_id = ? AND client_id = ?",
                (tenant_id, client_id),
            ).fetchone()
            if client_row is None:
                raise KeyError(client_id)
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, tenant_id, client_id, title, description, task_type, status, priority,
                    source_type, source_id, owner_user_id, due_at, created_at, updated_at, completed_at, dismissed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.tenant_id,
                    task.client_id,
                    task.title,
                    task.description,
                    task.task_type,
                    task.status.value,
                    task.priority,
                    task.source_type,
                    task.source_id,
                    task.owner_user_id,
                    task.due_at.isoformat() if task.due_at else None,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    None,
                    None,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="task_created",
                object_type="task",
                object_id=task.task_id,
                before={},
                after=self._audit_payload(task),
                correlation_id=correlation_id,
            )
        return task

    def list_tasks(
        self,
        tenant_id: str,
        client_id: str | None = None,
        *,
        status: TaskStatus | None = None,
        source_type: str | None = None,
        limit: int | None = None,
    ) -> list[Task]:
        query = "SELECT * FROM tasks WHERE tenant_id = ?"
        params: list[object] = [tenant_id]
        if client_id is not None:
            query += " AND client_id = ?"
            params.append(client_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if source_type is not None:
            query += " AND source_type = ?"
            params.append(source_type)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._task_from_row(dict(row)) for row in rows]

    def get_task(self, tenant_id: str, task_id: str) -> Task:
        with self._connect(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE tenant_id = ? AND task_id = ?",
                (tenant_id, task_id),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(dict(row))

    def update_task_status(
        self,
        tenant_id: str,
        task_id: str,
        *,
        status: TaskStatus,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Task:
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE tenant_id = ? AND task_id = ?",
                (tenant_id, task_id),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            existing = self._task_from_row(dict(row))
            updated = Task(
                task_id=existing.task_id,
                tenant_id=existing.tenant_id,
                client_id=existing.client_id,
                title=existing.title,
                description=existing.description,
                task_type=existing.task_type,
                status=status,
                priority=existing.priority,
                source_type=existing.source_type,
                source_id=existing.source_id,
                owner_user_id=existing.owner_user_id,
                due_at=existing.due_at,
                created_at=existing.created_at,
                updated_at=now,
                completed_at=now if status is TaskStatus.DONE else existing.completed_at,
                dismissed_at=now if status is TaskStatus.DISMISSED else existing.dismissed_at,
            )
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, completed_at = ?, dismissed_at = ?
                WHERE tenant_id = ? AND task_id = ?
                """,
                (
                    updated.status.value,
                    updated.updated_at.isoformat(),
                    updated.completed_at.isoformat() if updated.completed_at else None,
                    updated.dismissed_at.isoformat() if updated.dismissed_at else None,
                    tenant_id,
                    task_id,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="task_status_updated",
                object_type="task",
                object_id=task_id,
                before=self._audit_payload(existing),
                after=self._audit_payload(updated),
                correlation_id=correlation_id,
            )
        return updated

    def update_task(
        self,
        tenant_id: str,
        task_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        owner_user_id: str | None = None,
        due_at: datetime | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Task:
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE tenant_id = ? AND task_id = ?",
                (tenant_id, task_id),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            existing = self._task_from_row(dict(row))
            updated = Task(
                task_id=existing.task_id,
                tenant_id=existing.tenant_id,
                client_id=existing.client_id,
                title=title if title is not None else existing.title,
                description=description if description is not None else existing.description,
                task_type=existing.task_type,
                status=existing.status,
                priority=priority if priority is not None else existing.priority,
                source_type=existing.source_type,
                source_id=existing.source_id,
                owner_user_id=owner_user_id if owner_user_id is not None else existing.owner_user_id,
                due_at=due_at if due_at is not None else existing.due_at,
                created_at=existing.created_at,
                updated_at=now,
                completed_at=existing.completed_at,
                dismissed_at=existing.dismissed_at,
            )
            conn.execute(
                """
                UPDATE tasks
                SET title = ?, description = ?, priority = ?, owner_user_id = ?, due_at = ?, updated_at = ?
                WHERE tenant_id = ? AND task_id = ?
                """,
                (
                    updated.title,
                    updated.description,
                    updated.priority,
                    updated.owner_user_id,
                    updated.due_at.isoformat() if updated.due_at else None,
                    updated.updated_at.isoformat(),
                    tenant_id,
                    task_id,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="task_updated",
                object_type="task",
                object_id=task_id,
                before=self._audit_payload(existing),
                after=self._audit_payload(updated),
                correlation_id=correlation_id,
            )
        return updated

    def create_blocker(
        self,
        tenant_id: str,
        client_id: str,
        *,
        title: str,
        description: str | None = None,
        blocker_type: str = "missing_info",
        source_type: str = "manual",
        source_id: str | None = None,
        owner_user_id: str | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Blocker:
        now = self.clock.now()
        blocker = Blocker(
            blocker_id=str(uuid4()),
            tenant_id=tenant_id,
            client_id=client_id,
            title=title,
            description=description,
            blocker_type=blocker_type,
            status=BlockerStatus.OPEN,
            source_type=source_type,
            source_id=source_id,
            owner_user_id=owner_user_id,
            created_at=now,
            updated_at=now,
        )
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            client_row = conn.execute(
                "SELECT client_id FROM clients WHERE tenant_id = ? AND client_id = ?",
                (tenant_id, client_id),
            ).fetchone()
            if client_row is None:
                raise KeyError(client_id)
            conn.execute(
                """
                INSERT INTO blockers (
                    blocker_id, tenant_id, client_id, title, description, blocker_type, status,
                    source_type, source_id, owner_user_id, created_at, updated_at, resolved_at, dismissed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    blocker.blocker_id,
                    blocker.tenant_id,
                    blocker.client_id,
                    blocker.title,
                    blocker.description,
                    blocker.blocker_type,
                    blocker.status.value,
                    blocker.source_type,
                    blocker.source_id,
                    blocker.owner_user_id,
                    blocker.created_at.isoformat(),
                    blocker.updated_at.isoformat(),
                    None,
                    None,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="blocker_created",
                object_type="blocker",
                object_id=blocker.blocker_id,
                before={},
                after=self._audit_payload(blocker),
                correlation_id=correlation_id,
            )
        return blocker

    def list_blockers(
        self,
        tenant_id: str,
        client_id: str | None = None,
        *,
        status: BlockerStatus | None = None,
        source_type: str | None = None,
        limit: int | None = None,
    ) -> list[Blocker]:
        query = "SELECT * FROM blockers WHERE tenant_id = ?"
        params: list[object] = [tenant_id]
        if client_id is not None:
            query += " AND client_id = ?"
            params.append(client_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if source_type is not None:
            query += " AND source_type = ?"
            params.append(source_type)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._blocker_from_row(dict(row)) for row in rows]

    def update_blocker_status(
        self,
        tenant_id: str,
        blocker_id: str,
        *,
        status: BlockerStatus,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> Blocker:
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM blockers WHERE tenant_id = ? AND blocker_id = ?",
                (tenant_id, blocker_id),
            ).fetchone()
            if row is None:
                raise KeyError(blocker_id)
            existing = self._blocker_from_row(dict(row))
            updated = Blocker(
                blocker_id=existing.blocker_id,
                tenant_id=existing.tenant_id,
                client_id=existing.client_id,
                title=existing.title,
                description=existing.description,
                blocker_type=existing.blocker_type,
                status=status,
                source_type=existing.source_type,
                source_id=existing.source_id,
                owner_user_id=existing.owner_user_id,
                created_at=existing.created_at,
                updated_at=now,
                resolved_at=now if status is BlockerStatus.RESOLVED else existing.resolved_at,
                dismissed_at=now if status is BlockerStatus.DISMISSED else existing.dismissed_at,
            )
            conn.execute(
                """
                UPDATE blockers
                SET status = ?, updated_at = ?, resolved_at = ?, dismissed_at = ?
                WHERE tenant_id = ? AND blocker_id = ?
                """,
                (
                    updated.status.value,
                    updated.updated_at.isoformat(),
                    updated.resolved_at.isoformat() if updated.resolved_at else None,
                    updated.dismissed_at.isoformat() if updated.dismissed_at else None,
                    tenant_id,
                    blocker_id,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="blocker_status_updated",
                object_type="blocker",
                object_id=blocker_id,
                before=self._audit_payload(existing),
                after=self._audit_payload(updated),
                correlation_id=correlation_id,
            )
        return updated

    def generate_notice_work(
        self,
        tenant_id: str,
        *,
        notice_id: str,
        title: str,
        source_url: str,
        source_label: str | None = None,
        summary: str | None = None,
        affected_clients: list[dict[str, object]],
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> dict[str, object]:
        notice = self.upsert_notice(
            tenant_id=tenant_id,
            notice_id=notice_id,
            title=title,
            source_url=source_url,
            source_label=source_label,
            summary=summary,
            status=NoticeStatus.QUEUED,
            actor=actor,
            actor_ip=actor_ip,
        )
        created_tasks: list[Task] = []
        created_blockers: list[Blocker] = []
        skipped_clients: list[dict[str, object]] = []
        for impact in affected_clients:
            client_id = str(impact["client_id"])
            auto_updated = bool(impact.get("auto_updated", False))
            needs_client_confirmation = bool(impact.get("needs_client_confirmation", False))
            missing_context = bool(impact.get("missing_context", False))
            reason = str(impact.get("reason") or "").strip()
            client = self.get_client(tenant_id, client_id)

            if auto_updated and not needs_client_confirmation and not missing_context:
                skipped_clients.append(
                    {
                        "client_id": client_id,
                        "client_name": client.name,
                        "disposition": "auto_updated_only",
                    }
                )
                continue

            source_id = f"{notice_id}:{client_id}"
            if needs_client_confirmation or missing_context:
                existing_blocker = self._find_open_blocker_for_notice_client(tenant_id, client_id, source_id)
                if existing_blocker is not None:
                    skipped_clients.append(
                        {
                            "client_id": client_id,
                            "client_name": client.name,
                            "disposition": "existing_blocker",
                        }
                    )
                    continue
                blocker_title = f"Resolve notice follow-up for {client.name}"
                blocker_description = self._build_notice_work_description(
                    title=title,
                    source_url=source_url,
                    reason=reason,
                    old_date=impact.get("old_date"),
                    new_date=impact.get("new_date"),
                )
                created_blockers.append(
                    self.create_blocker(
                        tenant_id=tenant_id,
                        client_id=client_id,
                        title=blocker_title,
                        description=blocker_description,
                        blocker_type="policy_review" if needs_client_confirmation else "missing_info",
                        source_type="notice",
                        source_id=source_id,
                        actor=actor,
                        actor_ip=actor_ip,
                    )
                )
                continue

            existing_task = self._find_open_task_for_notice_client(tenant_id, client_id, source_id)
            if existing_task is not None:
                skipped_clients.append(
                    {
                        "client_id": client_id,
                        "client_name": client.name,
                        "disposition": "existing_task",
                    }
                )
                continue
            task_title = f"Review notice impact for {client.name}"
            task_description = self._build_notice_work_description(
                title=title,
                source_url=source_url,
                reason=reason,
                old_date=impact.get("old_date"),
                new_date=impact.get("new_date"),
            )
            created_tasks.append(
                self.create_task(
                    tenant_id=tenant_id,
                    client_id=client_id,
                    title=task_title,
                    description=task_description,
                    task_type="review",
                    priority="high",
                    source_type="notice",
                    source_id=source_id,
                    actor=actor,
                    actor_ip=actor_ip,
                )
            )
        next_status = NoticeStatus.AUTO_UPDATED
        if created_tasks or created_blockers:
            next_status = NoticeStatus.ESCALATED
        elif any(item["disposition"] != "auto_updated_only" for item in skipped_clients):
            next_status = NoticeStatus.ESCALATED
        notice = self.update_notice_status(
            tenant_id=tenant_id,
            notice_id=notice.notice_id,
            status=next_status,
            actor=actor,
            actor_ip=actor_ip,
        )
        return {
            "notice": notice,
            "notice_id": notice.notice_id,
            "title": notice.title,
            "source_url": notice.source_url,
            "tasks": created_tasks,
            "blockers": created_blockers,
            "skipped_clients": skipped_clients,
        }

    def upsert_notice(
        self,
        *,
        tenant_id: str,
        notice_id: str,
        title: str,
        source_url: str,
        source_label: str | None = None,
        summary: str | None = None,
        status: NoticeStatus = NoticeStatus.QUEUED,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> NoticeRecord:
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM notices WHERE tenant_id = ? AND notice_id = ?",
                (tenant_id, notice_id),
            ).fetchone()
            existing = self._notice_from_row(dict(row)) if row is not None else None
            notice = NoticeRecord(
                notice_id=notice_id,
                tenant_id=tenant_id,
                title=title,
                source_url=source_url,
                source_label=source_label if source_label is not None else (existing.source_label if existing else None),
                summary=summary if summary is not None else (existing.summary if existing else None),
                status=status if existing is None else existing.status,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                read_at=existing.read_at if existing else None,
                dismissed_at=existing.dismissed_at if existing else None,
            )
            conn.execute(
                """
                INSERT INTO notices (
                    notice_id, tenant_id, title, source_url, source_label, summary, status,
                    created_at, updated_at, read_at, dismissed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(notice_id) DO UPDATE SET
                    title = excluded.title,
                    source_url = excluded.source_url,
                    source_label = excluded.source_label,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (
                    notice.notice_id,
                    notice.tenant_id,
                    notice.title,
                    notice.source_url,
                    notice.source_label,
                    notice.summary,
                    notice.status.value,
                    notice.created_at.isoformat(),
                    notice.updated_at.isoformat(),
                    notice.read_at.isoformat() if notice.read_at else None,
                    notice.dismissed_at.isoformat() if notice.dismissed_at else None,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="notice_upserted",
                object_type="notice",
                object_id=notice.notice_id,
                before={} if existing is None else self._audit_payload(existing),
                after=self._audit_payload(notice),
                correlation_id=correlation_id,
            )
        return notice

    def list_notices(self, tenant_id: str, *, status: NoticeStatus | None = None, limit: int | None = None) -> list[NoticeRecord]:
        query = "SELECT * FROM notices WHERE tenant_id = ?"
        params: list[object] = [tenant_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY updated_at DESC, created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._notice_from_row(dict(row)) for row in rows]

    def update_notice_status(
        self,
        tenant_id: str,
        notice_id: str,
        *,
        status: NoticeStatus,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> NoticeRecord:
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM notices WHERE tenant_id = ? AND notice_id = ?",
                (tenant_id, notice_id),
            ).fetchone()
            if row is None:
                raise KeyError(notice_id)
            existing = self._notice_from_row(dict(row))
            updated = NoticeRecord(
                notice_id=existing.notice_id,
                tenant_id=existing.tenant_id,
                title=existing.title,
                source_url=existing.source_url,
                source_label=existing.source_label,
                summary=existing.summary,
                status=status,
                created_at=existing.created_at,
                updated_at=now,
                read_at=now if status is NoticeStatus.READ else existing.read_at,
                dismissed_at=now if status is NoticeStatus.DISMISSED else existing.dismissed_at,
            )
            conn.execute(
                """
                UPDATE notices
                SET status = ?, updated_at = ?, read_at = ?, dismissed_at = ?
                WHERE tenant_id = ? AND notice_id = ?
                """,
                (
                    updated.status.value,
                    updated.updated_at.isoformat(),
                    updated.read_at.isoformat() if updated.read_at else None,
                    updated.dismissed_at.isoformat() if updated.dismissed_at else None,
                    tenant_id,
                    notice_id,
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="notice_status_updated",
                object_type="notice",
                object_id=notice_id,
                before=self._audit_payload(existing),
                after=self._audit_payload(updated),
                correlation_id=correlation_id,
            )
        return updated

    def notice_payload(self, tenant_id: str, notice_id: str) -> dict[str, object]:
        with self._connect(tenant_id=tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM notices WHERE tenant_id = ? AND notice_id = ?",
                (tenant_id, notice_id),
            ).fetchone()
        if row is None:
            raise KeyError(notice_id)
        notice = self._notice_from_row(dict(row))
        tasks = [
            task
            for task in self.list_tasks(tenant_id, source_type="notice")
            if task.source_id and task.source_id.startswith(f"{notice_id}:")
        ]
        blockers = [
            blocker
            for blocker in self.list_blockers(tenant_id, source_type="notice")
            if blocker.source_id and blocker.source_id.startswith(f"{notice_id}:")
        ]
        return {
            "notice": notice,
            "tasks": tasks,
            "blockers": blockers,
        }

    def review_impact_payload(self, tenant_id: str, *, limit: int = 50) -> dict[str, object]:
        """Return a review-ready view of source interpretation and portfolio impact.

        This is intentionally backend-derived: official source metadata comes
        from the source registry, low-confidence interpretation comes from the
        parser payload, and notice outcomes come from generated tasks/blockers.
        The frontend can still fall back to mock data, but it no longer needs
        hard-coded source copy to demo the review chain.
        """
        clients = self.list_clients(tenant_id)
        clients_by_id = {client.client_id: client for client in clients}
        deadlines = self.list_deadlines(tenant_id)
        deadline_lookup = {deadline.deadline_id: deadline for deadline in deadlines}
        review_items = self.list_rule_review_queue()[:limit]
        notices = self.list_notices(tenant_id, limit=limit)
        rules = self.list_rules()[:limit]

        return {
            "tenant_id": tenant_id,
            "source_health": self._review_source_health(),
            "rule_reviews": [
                self._review_item_payload(item, clients=clients, deadlines=deadlines)
                for item in review_items
            ],
            "notices": [
                self._notice_review_payload(notice, clients_by_id=clients_by_id)
                for notice in notices
            ],
            "active_rules": [
                self._active_rule_payload(rule, deadlines=deadlines, clients_by_id=clients_by_id)
                for rule in rules
            ],
            "totals": {
                "review_items": len(review_items),
                "notices": len(notices),
                "active_rules": len(rules),
                "affected_clients": len(
                    {
                        impact["client_id"]
                        for notice in notices
                        for impact in self._notice_client_impacts(notice, clients_by_id=clients_by_id)
                        if impact.get("client_id")
                    }
                ),
                "visible_deadlines": len(deadline_lookup),
            },
        }

    def interpret_policy_change(
        self,
        tenant_id: str,
        *,
        raw_text: str,
        source_url: str,
        source: str | None = None,
        state: str | None = None,
        fetched_at: datetime | None = None,
    ) -> dict[str, object]:
        fetched_at = fetched_at or self.clock.now()
        source_definition = source_for_selector(source=source, state=state) if (source or state) else None
        parsed = self.parse_rule_text(
            raw_text,
            source_key=source_definition.source_key if source_definition else None,
            source_url=source_url,
            fetched_at=fetched_at,
        )
        clients = self.list_clients(tenant_id)
        deadlines = self.list_deadlines(tenant_id)
        parse_payload = parsed.extracted_fields
        missing_fields = self._missing_rule_parse_fields(parse_payload)
        return {
            "tenant_id": tenant_id,
            "provider": AIAssistService().provider_label,
            "source": self._source_metadata_for_url(source_url),
            "source_url": source_url,
            "fetched_at": fetched_at.isoformat(),
            "interpretation": {
                "summary": self._review_summary(parse_payload, missing_fields),
                "confidence_score": parsed.confidence_score,
                "extracted_fields": parse_payload,
                "missing_fields": missing_fields,
            },
            "affected_clients": self._matched_clients_for_parse_payload(parse_payload, clients=clients, deadlines=deadlines),
            "ready_to_apply": parsed.confidence_score >= 0.85 and not missing_fields,
        }

    def update_client_tax_profile(
        self,
        tenant_id: str,
        client_id: str,
        tax_year: int,
        *,
        entity_election: str | None = None,
        first_year_filing: bool | None = None,
        final_year_filing: bool | None = None,
        extension_requested: bool | None = None,
        extension_filed: bool | None = None,
        estimated_tax_required: bool | None = None,
        payroll_present: bool | None = None,
        contractor_reporting_required: bool | None = None,
        notice_received: bool | None = None,
        intake_status: str | None = None,
        profile_source: str | None = None,
        actor: str = "system",
        actor_ip: str = "127.0.0.1",
    ) -> ClientTaxProfile:
        now = self.clock.now()
        correlation_id = str(uuid4())
        with self._transaction(tenant_id=tenant_id) as conn:
            client_row = conn.execute(
                "SELECT * FROM clients WHERE tenant_id = ? AND client_id = ?",
                (tenant_id, client_id),
            ).fetchone()
            if client_row is None:
                raise KeyError(client_id)
            existing_row = conn.execute(
                """
                SELECT * FROM client_tax_profiles
                WHERE tenant_id = ? AND client_id = ? AND tax_year = ?
                """,
                (tenant_id, client_id, tax_year),
            ).fetchone()
            existing = self._client_tax_profile_from_row(dict(existing_row)) if existing_row else None
            profile = ClientTaxProfile(
                profile_id=existing.profile_id if existing else str(uuid4()),
                tenant_id=tenant_id,
                client_id=client_id,
                tax_year=tax_year,
                entity_election=entity_election if entity_election is not None else (existing.entity_election if existing else None),
                first_year_filing=first_year_filing if first_year_filing is not None else (existing.first_year_filing if existing else None),
                final_year_filing=final_year_filing if final_year_filing is not None else (existing.final_year_filing if existing else None),
                extension_requested=extension_requested if extension_requested is not None else (existing.extension_requested if existing else None),
                extension_filed=extension_filed if extension_filed is not None else (existing.extension_filed if existing else None),
                estimated_tax_required=estimated_tax_required if estimated_tax_required is not None else (existing.estimated_tax_required if existing else None),
                payroll_present=payroll_present if payroll_present is not None else (existing.payroll_present if existing else None),
                contractor_reporting_required=contractor_reporting_required if contractor_reporting_required is not None else (existing.contractor_reporting_required if existing else None),
                notice_received=notice_received if notice_received is not None else (existing.notice_received if existing else None),
                intake_status=intake_status if intake_status is not None else (existing.intake_status if existing else "draft"),
                source=profile_source if profile_source is not None else (existing.source if existing else "manual"),
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._upsert_client_tax_profile(conn, profile)
            self._insert_audit(
                conn=conn,
                tenant_id=tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="client_tax_profile_updated",
                object_type="client_tax_profile",
                object_id=profile.profile_id,
                before={} if existing is None else self._audit_payload(existing),
                after=self._audit_payload(profile),
                correlation_id=correlation_id,
            )
        self._publish(
            EventType.CLIENT_UPDATED,
            {"tenant_id": tenant_id, "client_id": client_id, "tax_year": tax_year, "profile_id": profile.profile_id},
            actor,
        )
        return profile

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

    def today_enriched(self, tenant_id: str, limit: int = 5) -> list[dict[str, object]]:
        today_items = self.today(tenant_id, limit=limit)
        clients = {client.client_id: client for client in self.list_clients(tenant_id)}
        today_date = self.clock.now().date()
        return [
            {
                "deadline_id": item.deadline_id,
                "client_id": item.client_id,
                "client_name": clients[item.client_id].name if item.client_id in clients else None,
                "tax_type": item.tax_type,
                "jurisdiction": item.jurisdiction,
                "due_date": item.due_date,
                "days_remaining": (datetime.fromisoformat(item.due_date).date() - today_date).days,
                "status": item.status.value,
            }
            for item in today_items
        ]

    def dashboard_payload(self, tenant_id: str, limit: int = 5) -> dict[str, object]:
        active_work = [
            task
            for task in self.list_tasks(tenant_id, limit=limit * 3)
            if task.status in {TaskStatus.OPEN, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}
        ][:limit]
        blockers = [
            blocker
            for blocker in self.list_blockers(tenant_id, limit=limit * 3)
            if blocker.status is BlockerStatus.OPEN
        ][:limit]
        return {
            "today": self.today_enriched(tenant_id, limit=limit),
            "active_work": active_work,
            "waiting_on_info": blockers,
            "client_count": len(self.list_clients(tenant_id)),
            "open_task_count": len(
                [task for task in self.list_tasks(tenant_id) if task.status in {TaskStatus.OPEN, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}]
            ),
            "open_blocker_count": len([blocker for blocker in self.list_blockers(tenant_id) if blocker.status is BlockerStatus.OPEN]),
        }

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

    def _queue_notification_deliveries(self, conn, reminder: Reminder, actor: str, actor_ip: str) -> None:
        routes = conn.execute(
            "SELECT * FROM notification_routes WHERE tenant_id = ? AND enabled = 1 ORDER BY created_at",
            (reminder.tenant_id,),
        ).fetchall()
        if not routes:
            return
        deadline_row = conn.execute(
            "SELECT * FROM deadlines WHERE deadline_id = ?",
            (reminder.deadline_id,),
        ).fetchone()
        client_row = conn.execute(
            "SELECT * FROM clients WHERE client_id = ?",
            (reminder.client_id,),
        ).fetchone()
        if deadline_row is None or client_row is None:
            return
        deadline = self._deadline_from_row(dict(deadline_row))
        client = self._client_from_row(dict(client_row))
        for route_row in routes:
            route = self._notification_route_from_row(dict(route_row))
            delivery = NotificationDelivery(
                delivery_id=str(uuid4()),
                tenant_id=reminder.tenant_id,
                client_id=reminder.client_id,
                deadline_id=reminder.deadline_id,
                reminder_id=reminder.reminder_id,
                channel=route.channel,
                destination=route.destination,
                subject=f"{client.name}: {deadline.tax_type} due {deadline.due_date}",
                body=self._build_notification_body(client, deadline, reminder),
                status=NotificationStatus.PENDING,
                provider_message_id=None,
                error_message=None,
                created_at=self.clock.now(),
                sent_at=None,
            )
            conn.execute(
                """
                INSERT INTO notification_deliveries (
                    delivery_id, tenant_id, client_id, deadline_id, reminder_id, channel, destination,
                    subject, body, status, provider_message_id, error_message, created_at, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL)
                """,
                (
                    delivery.delivery_id,
                    delivery.tenant_id,
                    delivery.client_id,
                    delivery.deadline_id,
                    delivery.reminder_id,
                    delivery.channel.value,
                    delivery.destination,
                    delivery.subject,
                    delivery.body,
                    delivery.status.value,
                    delivery.created_at.isoformat(),
                ),
            )
            self._insert_audit(
                conn=conn,
                tenant_id=delivery.tenant_id,
                actor=actor,
                actor_ip=actor_ip,
                action_type="notification_delivery_created",
                object_type="notification_delivery",
                object_id=delivery.delivery_id,
                before={},
                after={"channel": delivery.channel.value, "destination": delivery.destination, "deadline_id": delivery.deadline_id},
                correlation_id=str(uuid4()),
            )

    def _build_notification_body(self, client: Client, deadline: Deadline, reminder: Reminder) -> str:
        return (
            f"Client: {client.name}\n"
            f"Tax type: {deadline.tax_type}\n"
            f"Jurisdiction: {deadline.jurisdiction}\n"
            f"Due date: {deadline.due_date}\n"
            f"Reminder: {reminder.reminder_day}\n"
            "Actions: complete / snooze / waive"
        )

    def _client_email_destination(self, tenant_id: str, client: Client) -> str | None:
        if client.primary_contact_email:
            return client.primary_contact_email
        bundle = self.get_client_bundle(tenant_id, client.client_id)
        contacts = bundle.get("contacts", [])
        primary = next((contact for contact in contacts if contact.is_primary and contact.email), None)
        if primary:
            return primary.email
        contact = next((contact for contact in contacts if contact.email), None)
        return contact.email if contact else None

    def _open_blocker_reason_for_client(self, tenant_id: str, client_id: str) -> str | None:
        blockers = [item for item in self.list_blockers(tenant_id, client_id) if item.status is BlockerStatus.OPEN]
        if not blockers:
            return None
        blocker = blockers[0]
        return f"{blocker.title}: {blocker.description}" if blocker.description else blocker.title

    def _email_target_deadline(self, tenant_id: str, client_id: str, deadline_id: str | None) -> Deadline:
        if deadline_id:
            deadline = self.get_deadline(tenant_id, deadline_id)
            if deadline.client_id != client_id:
                raise ValueError("deadline does not belong to client")
            return deadline
        deadlines = [
            deadline
            for deadline in self.list_deadlines(tenant_id, client_id=client_id)
            if deadline.status in {DeadlineStatus.PENDING, DeadlineStatus.SNOOZED, DeadlineStatus.OVERRIDDEN}
        ]
        if not deadlines:
            raise ValueError("client has no active deadline to anchor this email")
        deadlines.sort(key=lambda item: (item.due_date, item.created_at))
        return deadlines[0]

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

    def _refresh_deadlines_for_rule(self, rule: RuleRecord, correlation_id: str, actor: str, actor_ip: str) -> None:
        with self._connect() as conn:
            tenant_rows = conn.execute("SELECT tenant_id FROM tenants WHERE is_deleted = 0 ORDER BY created_at").fetchall()
        for tenant_row in tenant_rows:
            tenant_id = tenant_row["tenant_id"]
            with self._transaction(tenant_id=tenant_id) as tenant_conn:
                rows = tenant_conn.execute(
                    "SELECT * FROM clients WHERE tenant_id = ? ORDER BY created_at",
                    (tenant_id,),
                ).fetchall()
                for row in rows:
                    client = self._client_from_row(dict(row))
                    if self._rule_matches_client(rule, client):
                        self._upsert_deadline_from_rule(tenant_conn, client, rule, correlation_id, actor, actor_ip)

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

    def _upsert_client_tax_profile(self, conn, profile: ClientTaxProfile) -> None:
        conn.execute(
            """
            INSERT INTO client_tax_profiles (
                profile_id, tenant_id, client_id, tax_year, entity_election,
                first_year_filing, final_year_filing, extension_requested, extension_filed,
                estimated_tax_required, payroll_present, contractor_reporting_required,
                notice_received, intake_status, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (client_id, tax_year) DO UPDATE SET
                entity_election = excluded.entity_election,
                first_year_filing = excluded.first_year_filing,
                final_year_filing = excluded.final_year_filing,
                extension_requested = excluded.extension_requested,
                extension_filed = excluded.extension_filed,
                estimated_tax_required = excluded.estimated_tax_required,
                payroll_present = excluded.payroll_present,
                contractor_reporting_required = excluded.contractor_reporting_required,
                notice_received = excluded.notice_received,
                intake_status = excluded.intake_status,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                profile.profile_id,
                profile.tenant_id,
                profile.client_id,
                profile.tax_year,
                profile.entity_election,
                self._bool_to_db(profile.first_year_filing),
                self._bool_to_db(profile.final_year_filing),
                self._bool_to_db(profile.extension_requested),
                self._bool_to_db(profile.extension_filed),
                self._bool_to_db(profile.estimated_tax_required),
                self._bool_to_db(profile.payroll_present),
                self._bool_to_db(profile.contractor_reporting_required),
                self._bool_to_db(profile.notice_received),
                profile.intake_status,
                profile.source,
                profile.created_at.isoformat(),
                profile.updated_at.isoformat(),
            ),
        )

    def _sync_client_jurisdictions(
        self,
        conn,
        *,
        tenant_id: str,
        client_id: str,
        tax_year: int,
        registered_states: list[str],
        home_jurisdiction: str | None,
        source: str,
    ) -> None:
        conn.execute(
            """
            DELETE FROM client_jurisdictions
            WHERE tenant_id = ? AND client_id = ? AND tax_year = ? AND jurisdiction_type IN ('resident', 'operating')
            """,
            (tenant_id, client_id, tax_year),
        )
        jurisdictions: list[ClientJurisdiction] = []
        if home_jurisdiction:
            jurisdictions.append(
                ClientJurisdiction(
                    client_jurisdiction_id=str(uuid4()),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    tax_year=tax_year,
                    jurisdiction=home_jurisdiction,
                    jurisdiction_type="resident",
                    active=True,
                    source=source,
                    notes=None,
                    created_at=self.clock.now(),
                )
            )
        for state in sorted({state.upper() for state in registered_states}):
            jurisdictions.append(
                ClientJurisdiction(
                    client_jurisdiction_id=str(uuid4()),
                    tenant_id=tenant_id,
                    client_id=client_id,
                    tax_year=tax_year,
                    jurisdiction=state,
                    jurisdiction_type="operating",
                    active=True,
                    source=source,
                    notes=None,
                    created_at=self.clock.now(),
                )
            )
        for jurisdiction in jurisdictions:
            conn.execute(
                """
                INSERT INTO client_jurisdictions (
                    client_jurisdiction_id, tenant_id, client_id, tax_year, jurisdiction,
                    jurisdiction_type, active, source, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (client_id, tax_year, jurisdiction, jurisdiction_type) DO UPDATE SET
                    active = excluded.active,
                    source = excluded.source,
                    notes = excluded.notes
                """,
                (
                    jurisdiction.client_jurisdiction_id,
                    jurisdiction.tenant_id,
                    jurisdiction.client_id,
                    jurisdiction.tax_year,
                    jurisdiction.jurisdiction,
                    jurisdiction.jurisdiction_type,
                    self._bool_to_db(jurisdiction.active),
                    jurisdiction.source,
                    jurisdiction.notes,
                    jurisdiction.created_at.isoformat(),
                ),
            )

    def _upsert_primary_client_contact(self, conn, contact: ClientContact | None) -> None:
        if contact is None:
            return
        conn.execute(
            "DELETE FROM client_contacts WHERE tenant_id = ? AND client_id = ? AND is_primary = ?",
            (contact.tenant_id, contact.client_id, self._bool_to_db(True)),
        )
        conn.execute(
            """
            INSERT INTO client_contacts (
                contact_id, tenant_id, client_id, name, role, email, phone,
                preferred_channel, is_primary, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact.contact_id,
                contact.tenant_id,
                contact.client_id,
                contact.name,
                contact.role,
                contact.email,
                contact.phone,
                contact.preferred_channel,
                self._bool_to_db(contact.is_primary),
                contact.created_at.isoformat(),
                contact.updated_at.isoformat(),
            ),
        )

    def _bool_to_db(self, value: bool | None) -> bool | int | None:
        if value is None:
            return None
        storage = self.repositories.storage
        if storage.__class__.__name__ == "SQLiteStorage":
            return int(value)
        return value

    def _db_to_bool(self, value: object) -> bool | None:
        if value is None:
            return None
        return bool(value)

    def _audit_payload(self, value: object) -> object:
        if is_dataclass(value):
            return self._audit_payload(asdict(value))
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: self._audit_payload(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._audit_payload(item) for item in value]
        return value

    def _decode_json_field(self, value: object, default: object) -> object:
        if value is None:
            return default
        if isinstance(value, str):
            return json.loads(value)
        return value

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
            registered_states=self._decode_json_field(row["registered_states"], default=[]),
            tax_year=row["tax_year"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
            client_type=row.get("client_type", "business"),
            legal_name=row.get("legal_name"),
            home_jurisdiction=row.get("home_jurisdiction"),
            primary_contact_name=row.get("primary_contact_name"),
            primary_contact_email=row.get("primary_contact_email"),
            primary_contact_phone=row.get("primary_contact_phone"),
            preferred_communication_channel=row.get("preferred_communication_channel"),
            responsible_cpa=row.get("responsible_cpa"),
            is_active=bool(row.get("is_active", True)),
        )

    def _client_tax_profile_from_row(self, row: dict) -> ClientTaxProfile:
        return ClientTaxProfile(
            profile_id=row["profile_id"],
            tenant_id=row["tenant_id"],
            client_id=row["client_id"],
            tax_year=row["tax_year"],
            entity_election=row.get("entity_election"),
            first_year_filing=self._db_to_bool(row.get("first_year_filing")),
            final_year_filing=self._db_to_bool(row.get("final_year_filing")),
            extension_requested=self._db_to_bool(row.get("extension_requested")),
            extension_filed=self._db_to_bool(row.get("extension_filed")),
            estimated_tax_required=self._db_to_bool(row.get("estimated_tax_required")),
            payroll_present=self._db_to_bool(row.get("payroll_present")),
            contractor_reporting_required=self._db_to_bool(row.get("contractor_reporting_required")),
            notice_received=self._db_to_bool(row.get("notice_received")),
            intake_status=row["intake_status"],
            source=row["source"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _client_jurisdiction_from_row(self, row: dict) -> ClientJurisdiction:
        return ClientJurisdiction(
            client_jurisdiction_id=row["client_jurisdiction_id"],
            tenant_id=row["tenant_id"],
            client_id=row["client_id"],
            tax_year=row["tax_year"],
            jurisdiction=row["jurisdiction"],
            jurisdiction_type=row["jurisdiction_type"],
            active=bool(row["active"]),
            source=row["source"],
            notes=row.get("notes"),
            created_at=self._parse_datetime(row["created_at"]),
        )

    def _client_contact_from_row(self, row: dict) -> ClientContact:
        return ClientContact(
            contact_id=row["contact_id"],
            tenant_id=row["tenant_id"],
            client_id=row["client_id"],
            name=row["name"],
            role=row.get("role"),
            email=row.get("email"),
            phone=row.get("phone"),
            preferred_channel=row.get("preferred_channel"),
            is_primary=bool(row["is_primary"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
        )

    def _task_from_row(self, row: dict) -> Task:
        return Task(
            task_id=row["task_id"],
            tenant_id=row["tenant_id"],
            client_id=row["client_id"],
            title=row["title"],
            description=row.get("description"),
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            source_type=row["source_type"],
            source_id=row.get("source_id"),
            owner_user_id=row.get("owner_user_id"),
            due_at=self._parse_datetime(row["due_at"]) if row.get("due_at") else None,
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
            completed_at=self._parse_datetime(row["completed_at"]) if row.get("completed_at") else None,
            dismissed_at=self._parse_datetime(row["dismissed_at"]) if row.get("dismissed_at") else None,
        )

    def _blocker_from_row(self, row: dict) -> Blocker:
        return Blocker(
            blocker_id=row["blocker_id"],
            tenant_id=row["tenant_id"],
            client_id=row["client_id"],
            title=row["title"],
            description=row.get("description"),
            blocker_type=row["blocker_type"],
            status=BlockerStatus(row["status"]),
            source_type=row["source_type"],
            source_id=row.get("source_id"),
            owner_user_id=row.get("owner_user_id"),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
            resolved_at=self._parse_datetime(row["resolved_at"]) if row.get("resolved_at") else None,
            dismissed_at=self._parse_datetime(row["dismissed_at"]) if row.get("dismissed_at") else None,
        )

    def _notice_from_row(self, row: dict) -> NoticeRecord:
        return NoticeRecord(
            notice_id=row["notice_id"],
            tenant_id=row["tenant_id"],
            title=row["title"],
            source_url=row["source_url"],
            source_label=row.get("source_label"),
            summary=row.get("summary"),
            status=NoticeStatus(row["status"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
            read_at=self._parse_datetime(row["read_at"]) if row.get("read_at") else None,
            dismissed_at=self._parse_datetime(row["dismissed_at"]) if row.get("dismissed_at") else None,
        )

    def _normalize_import_row(self, headers: list[str], row: list[str]) -> list[str]:
        if len(row) < len(headers):
            return row + [""] * (len(headers) - len(row))
        if len(row) > len(headers):
            return row[: len(headers)]
        return row

    def _analyze_import_headers(self, headers: list[str]) -> tuple[list[dict[str, object]], dict[str, int], list[str]]:
        normalized_headers = [self._normalize_import_header(header) for header in headers]
        used_indexes: set[int] = set()
        mappings: list[dict[str, object]] = []
        matched_targets: dict[str, int] = {}
        for spec in IMPORT_FIELD_SPECS:
            best_index = None
            best_confidence = 0.0
            for index, normalized_header in enumerate(normalized_headers):
                if index in used_indexes:
                    continue
                confidence = self._score_import_header_match(normalized_header, spec["aliases"])
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_index = index
            if best_index is not None and best_confidence >= 0.82:
                used_indexes.add(best_index)
                matched_targets[spec["key"]] = best_index
                mappings.append(
                    {
                        "target_field": spec["target_field"],
                        "source_column": headers[best_index],
                        "confidence": round(best_confidence, 2),
                        "status": "Mapped",
                    }
                )
            else:
                mappings.append(
                    {
                        "target_field": spec["target_field"],
                        "source_column": "",
                        "confidence": 0,
                        "status": "Needs follow-up",
                    }
                )
        extra_columns = [headers[index] for index in range(len(headers)) if index not in used_indexes]
        return mappings, matched_targets, extra_columns

    def _apply_import_mapping_overrides(
        self,
        headers: list[str],
        *,
        mappings: list[dict[str, object]],
        matched_targets: dict[str, int],
        mapping_overrides: dict[str, str],
    ) -> tuple[list[dict[str, object]], dict[str, int], list[str]]:
        target_by_label = {
            self._normalize_import_header(str(spec["target_field"])): str(spec["key"])
            for spec in IMPORT_FIELD_SPECS
        }
        target_by_key = {str(spec["key"]): str(spec["key"]) for spec in IMPORT_FIELD_SPECS}
        source_index_by_header = {self._normalize_import_header(header): index for index, header in enumerate(headers)}
        next_targets = dict(matched_targets)
        for raw_header, raw_target in mapping_overrides.items():
            header_key = self._normalize_import_header(raw_header)
            target_key = self._normalize_import_header(raw_target).replace(" ", "_")
            header_index = source_index_by_header.get(header_key)
            if header_index is None:
                continue
            for existing_target, existing_index in list(next_targets.items()):
                if existing_index == header_index:
                    next_targets.pop(existing_target)
            if target_key in {"skip", "ignore", "custom"}:
                continue
            resolved_target = target_by_key.get(target_key) or target_by_label.get(self._normalize_import_header(raw_target))
            if resolved_target:
                next_targets[resolved_target] = header_index

        used_indexes = set(next_targets.values())
        next_mappings: list[dict[str, object]] = []
        for spec in IMPORT_FIELD_SPECS:
            target_key = str(spec["key"])
            index = next_targets.get(target_key)
            if index is None:
                next_mappings.append(
                    {
                        "target_field": spec["target_field"],
                        "source_column": "",
                        "confidence": 0,
                        "status": "Needs follow-up",
                    }
                )
                continue
            next_mappings.append(
                {
                    "target_field": spec["target_field"],
                    "source_column": headers[index],
                    "confidence": 1.0,
                    "status": "Mapped",
                    "override": True,
                }
            )
        extra_columns = [headers[index] for index in range(len(headers)) if index not in used_indexes]
        return next_mappings, next_targets, extra_columns

    def _build_import_ai_assist(
        self,
        *,
        headers: list[str],
        rows: list[list[str]],
        mappings: list[dict[str, object]],
        matched_targets: dict[str, int],
        missing_fields: list[str],
    ) -> dict[str, object]:
        normalized_clients = []
        for index, row in enumerate(rows[:5], start=2):
            client_name = self._extract_import_value(row, matched_targets.get("client_name"))
            entity_type = self._extract_import_value(row, matched_targets.get("entity_type"))
            states = self._split_import_states(self._extract_import_value(row, matched_targets.get("operating_states")))
            normalized_clients.append(
                {
                    "row_number": index,
                    "client_name": client_name or None,
                    "entity_type": self._normalize_import_entity_type(entity_type) if entity_type else None,
                    "registered_states": states,
                    "ready": bool(client_name and entity_type and states),
                }
            )
        suggestions = [
            {
                "target_field": item["target_field"],
                "source_column": item["source_column"],
                "confidence": item["confidence"],
                "reason": "Matched from header aliases and row shape.",
            }
            for item in mappings
            if item.get("source_column")
        ]
        return {
            "provider": AIAssistService().provider_label,
            "summary": (
                "Import structure is ready for plan generation."
                if not missing_fields
                else f"Import needs review: {', '.join(missing_fields[:3])}."
            ),
            "mapping_suggestions": suggestions,
            "normalized_clients": normalized_clients,
            "supports_manual_overrides": True,
        }

    def _normalize_import_header(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()

    def _score_import_header_match(self, normalized_header: str, aliases: tuple[str, ...]) -> float:
        best = 0.0
        for alias in aliases:
            normalized_alias = self._normalize_import_header(alias)
            if normalized_header == normalized_alias:
                best = max(best, 0.98)
            elif normalized_alias and normalized_alias in normalized_header:
                best = max(best, 0.91)
            elif normalized_header and normalized_header in normalized_alias:
                best = max(best, 0.86)
        return best

    def _build_import_missing_fields(self, rows: list[list[str]], matched_targets: dict[str, int]) -> list[str]:
        messages: list[str] = []
        required_specs = [spec for spec in IMPORT_FIELD_SPECS if spec["required"]]
        for spec in required_specs:
            if spec["key"] not in matched_targets:
                messages.append(f"Map a column for {spec['target_field']}.")
        if "home_jurisdiction" not in matched_targets:
            sample_names = self._import_sample_client_names(rows, matched_targets.get("client_name"))
            if sample_names:
                messages.append(f"Confirm home jurisdiction for {sample_names[0]}.")
        for target_key, label in (
            ("client_name", "client name"),
            ("entity_type", "entity type"),
            ("operating_states", "operating states"),
            ("home_jurisdiction", "home jurisdiction"),
        ):
            column_index = matched_targets.get(target_key)
            if column_index is None:
                continue
            for row_index, row in enumerate(rows[:5]):
                value = row[column_index].strip() if column_index < len(row) else ""
                if value:
                    continue
                display_name = self._import_client_label_for_row(
                    row=row,
                    row_index=row_index,
                    client_name_index=matched_targets.get("client_name"),
                )
                messages.append(f"Confirm {display_name} {label}.")
                break
        deduped: list[str] = []
        seen: set[str] = set()
        for message in messages:
            if message in seen:
                continue
            seen.add(message)
            deduped.append(message)
        return deduped[:5]

    def _match_optional_import_column(self, headers: list[str], aliases: tuple[str, ...]) -> int | None:
        normalized_headers = [self._normalize_import_header(header) for header in headers]
        best_index = None
        best_confidence = 0.0
        for index, normalized_header in enumerate(normalized_headers):
            confidence = self._score_import_header_match(normalized_header, aliases)
            if confidence > best_confidence:
                best_confidence = confidence
                best_index = index
        if best_index is None or best_confidence < 0.82:
            return None
        return best_index

    def _extract_import_value(self, row: list[str], index: int | None) -> str:
        if index is None or index >= len(row):
            return ""
        return row[index].strip()

    def _split_import_states(self, raw_value: str) -> list[str]:
        candidates = re.split(r"[,/;|]+", raw_value)
        states: list[str] = []
        for item in candidates:
            normalized = item.strip().upper()
            if not normalized or normalized in {"-", "—", "N/A"}:
                continue
            states.append(normalized)
        deduped: list[str] = []
        seen: set[str] = set()
        for state in states:
            if state in seen:
                continue
            seen.add(state)
            deduped.append(state)
        return deduped

    def _normalize_import_entity_type(self, raw_value: str) -> str:
        normalized = raw_value.strip().lower()
        replacements = {
            "c corp": "c-corp",
            "c-corp": "c-corp",
            "s corp": "s-corp",
            "s-corp": "s-corp",
            "sole prop": "sole-prop",
            "sole proprietorship": "sole-prop",
        }
        return replacements.get(normalized, normalized.replace(" ", "-"))

    def _infer_client_type(self, raw_entity_type: str, default_client_type: str) -> str:
        normalized = raw_entity_type.strip().lower()
        if normalized in {"individual", "1040", "personal"}:
            return "individual"
        return default_client_type

    def _generate_import_blockers_for_client(
        self,
        *,
        client: Client,
        row: list[str],
        row_number: int,
        matched_targets: dict[str, int],
        actor: str,
        actor_ip: str,
    ) -> list[Blocker]:
        blockers: list[Blocker] = []
        home_jurisdiction = self._extract_import_value(row, matched_targets.get("home_jurisdiction"))
        if not home_jurisdiction:
            blockers.append(
                self.create_blocker(
                    tenant_id=client.tenant_id,
                    client_id=client.client_id,
                    title=f"Confirm home jurisdiction for {client.name}",
                    description=f"Imported row {row_number} did not include a reliable home jurisdiction value.",
                    blocker_type="missing_info",
                    source_type="import",
                    source_id=f"import-home-jurisdiction:{client.client_id}",
                    actor=actor,
                    actor_ip=actor_ip,
                )
            )
        return blockers

    def _generate_import_tasks_for_client(self, *, client: Client, actor: str, actor_ip: str) -> list[Task]:
        tasks: list[Task] = []
        today = self.clock.now().date()
        for deadline in self.list_deadlines(client.tenant_id, client.client_id, within_days=14):
            if deadline.status is not DeadlineStatus.PENDING:
                continue
            due_date = datetime.fromisoformat(deadline.due_date).date()
            if (due_date - today).days < 0:
                continue
            source_id = deadline.deadline_id
            existing = self._find_open_task_for_source(client.tenant_id, client.client_id, "deadline", source_id)
            if existing is not None:
                continue
            tasks.append(
                self.create_task(
                    tenant_id=client.tenant_id,
                    client_id=client.client_id,
                    title=f"Prepare {deadline.tax_type} for {client.name}",
                    description=f"Generated from imported profile because the deadline is due on {deadline.due_date}.",
                    task_type="deadline_action",
                    priority="high" if (due_date - today).days <= 7 else "normal",
                    source_type="deadline",
                    source_id=deadline.deadline_id,
                    actor=actor,
                    actor_ip=actor_ip,
                )
            )
        return tasks

    def _build_import_plan_for_clients(self, *, tenant_id: str, clients: list[Client]) -> list[ProposedPlanItem]:
        items: list[ProposedPlanItem] = []
        for client in clients:
            open_blockers = [blocker for blocker in self.list_blockers(tenant_id, client.client_id) if blocker.status is BlockerStatus.OPEN]
            blocker_text = " ".join(
                filter(
                    None,
                    [f"{blocker.title} {blocker.description or ''}".strip() for blocker in open_blockers],
                )
            ).lower()
            for deadline in self.list_deadlines(tenant_id, client.client_id):
                if deadline.status is not DeadlineStatus.PENDING:
                    continue
                recommendation = self._recommend_import_plan_step(deadline=deadline, blocker_text=blocker_text)
                items.append(
                    ProposedPlanItem(
                        plan_item_id=str(uuid4()),
                        tenant_id=tenant_id,
                        client_id=client.client_id,
                        deadline_id=deadline.deadline_id,
                        client_name=client.name,
                        task_title=recommendation["task_title"],
                        tax_type=deadline.tax_type,
                        jurisdiction=deadline.jurisdiction,
                        related_due_date=deadline.due_date,
                        recommended_window=recommendation["recommended_window"],
                        reason=recommendation["reason"],
                        urgency=recommendation["urgency"],
                        default_action="now" if recommendation["urgency"] == "urgent" else "later",
                    )
                )
        items.sort(key=lambda item: ({"urgent": 0, "medium": 1, "low": 2}.get(item.urgency, 3), item.related_due_date, item.client_name))
        return items

    def _recommend_import_plan_step(self, *, deadline: Deadline, blocker_text: str) -> dict[str, str]:
        due_date = datetime.fromisoformat(deadline.due_date).date()
        days_remaining = (due_date - self.clock.now().date()).days
        if blocker_text and any(token in blocker_text for token in ("missing", "pending", "blocking", "confirm")):
            return {
                "task_title": f"Collect required info for {deadline.tax_type}",
                "recommended_window": "do_now" if days_remaining <= 7 else "this_week",
                "urgency": "urgent" if days_remaining <= 7 else "medium",
                "reason": "An imported blocker suggests missing or pending information before filing can move.",
            }
        if days_remaining <= 3:
            return {
                "task_title": f"Complete {deadline.tax_type}",
                "recommended_window": "do_now",
                "urgency": "urgent",
                "reason": "The final filing deadline is close enough that this should be completed immediately.",
            }
        if days_remaining <= 14:
            return {
                "task_title": f"Prepare {deadline.tax_type}",
                "recommended_window": "this_week",
                "urgency": "medium",
                "reason": "This filing is approaching and should move into preparation this week.",
            }
        return {
            "task_title": f"Confirm filing scope for {deadline.tax_type}",
            "recommended_window": "next_week",
            "urgency": "low",
            "reason": "This filing is far enough out that CPA can confirm scope and schedule the work deliberately.",
        }

    def _planned_due_at_for_window(self, planned_window: str, *, related_due_date: str) -> datetime:
        now = self.clock.now()
        normalized = planned_window.lower()
        offsets = {
            "do_now": timedelta(hours=0),
            "now": timedelta(hours=0),
            "tomorrow": timedelta(days=1),
            "this_week": timedelta(days=3),
            "next_week": timedelta(days=7),
            "two_weeks": timedelta(days=14),
            "in_two_weeks": timedelta(days=14),
        }
        candidate = now + offsets.get(normalized, timedelta(days=7))
        related_due = datetime.fromisoformat(related_due_date).replace(tzinfo=timezone.utc)
        return candidate if candidate <= related_due else related_due

    def _coerce_proposed_plan_item(self, payload: dict[str, object]) -> ProposedPlanItem:
        return ProposedPlanItem(
            plan_item_id=str(payload["plan_item_id"]),
            tenant_id=str(payload["tenant_id"]),
            client_id=str(payload["client_id"]),
            deadline_id=str(payload["deadline_id"]),
            client_name=str(payload["client_name"]),
            task_title=str(payload["task_title"]),
            tax_type=str(payload["tax_type"]),
            jurisdiction=str(payload["jurisdiction"]),
            related_due_date=str(payload["related_due_date"]),
            recommended_window=str(payload["recommended_window"]),
            reason=str(payload["reason"]),
            urgency=str(payload["urgency"]),
            default_action=str(payload.get("default_action", "later")),
        )

    def _import_sample_client_names(self, rows: list[list[str]], client_name_index: int | None) -> list[str]:
        if client_name_index is None:
            return []
        names: list[str] = []
        for row in rows:
            if client_name_index >= len(row):
                continue
            name = row[client_name_index].strip()
            if not name:
                continue
            names.append(name)
            if len(names) == 3:
                break
        return names

    def _import_client_label_for_row(self, *, row: list[str], row_index: int, client_name_index: int | None) -> str:
        if client_name_index is not None and client_name_index < len(row):
            name = row[client_name_index].strip()
            if name:
                return name
        return f"row {row_index + 1}"

    def _build_import_summary(
        self,
        *,
        imported_rows: int,
        resolved_required_mappings: int,
        required_mappings: int,
        missing_count: int,
    ) -> str:
        if imported_rows == 0:
            return "No rows were imported yet."
        if resolved_required_mappings == required_mappings and missing_count == 0:
            return "The core filing-profile fields are mapped cleanly, so this file is ready to generate a dashboard."
        if resolved_required_mappings == required_mappings:
            return (
                "The required columns are mapped, but a few client-level gaps still need CPA confirmation before the "
                "queue should be trusted."
            )
        return (
            f"The file has {imported_rows} client rows, but only {resolved_required_mappings} of the "
            f"{required_mappings} required filing-profile fields are mapped so far."
        )

    def _build_notice_work_description(
        self,
        *,
        title: str,
        source_url: str,
        reason: str,
        old_date: object | None,
        new_date: object | None,
    ) -> str:
        parts = [f"Notice: {title}", f"Source: {source_url}"]
        if old_date or new_date:
            parts.append(f"Date change: {old_date or 'unknown'} -> {new_date or 'unknown'}")
        if reason:
            parts.append(f"Why this needs attention: {reason}")
        return "\n".join(parts)

    def _review_source_health(self) -> dict[str, object]:
        sources = official_source_registry()
        fetch_runs = self.list_fetch_runs()
        latest_fetch = fetch_runs[0] if fetch_runs else None
        return {
            "official_source_count": len(sources),
            "monitored_jurisdictions": len({item.jurisdiction for item in sources.values()}),
            "latest_fetch_status": latest_fetch.status if latest_fetch else None,
            "latest_fetch_source": latest_fetch.source_key if latest_fetch else None,
            "latest_fetch_at": latest_fetch.fetched_at.isoformat() if latest_fetch else None,
            "demo_ready_sources": [
                self._source_metadata_for_url("https://www.ftb.ca.gov/about-ftb/newsroom/index.html"),
                self._source_metadata_for_url("https://comptroller.texas.gov/about/media-center/news/index.php"),
                self._source_metadata_for_url("https://www.tax.ny.gov/press/"),
            ],
        }

    def _review_item_payload(
        self,
        item: RuleReviewItem,
        *,
        clients: list[Client],
        deadlines: list[Deadline],
    ) -> dict[str, object]:
        parse_payload = item.parse_payload or {}
        missing_fields = self._missing_rule_parse_fields(parse_payload)
        affected_clients = self._matched_clients_for_parse_payload(parse_payload, clients=clients, deadlines=deadlines)
        extracted = {
            key: value
            for key, value in parse_payload.items()
            if value not in (None, "", [])
        }
        extracted_label = ", ".join(sorted(extracted)) if extracted else "no structured fields"
        return {
            "review_id": item.review_id,
            "source": self._source_metadata_for_url(item.source_url),
            "source_url": item.source_url,
            "fetched_at": item.fetched_at.isoformat(),
            "confidence_score": item.confidence_score,
            "status": "needs_cpa_review",
            "interpretation": {
                "summary": self._review_summary(parse_payload, missing_fields),
                "extracted_fields": parse_payload,
                "missing_fields": missing_fields,
                "reason": (
                    f"Parser extracted {extracted_label}, but needs CPA review before this can change the portfolio."
                    if missing_fields
                    else "Parser found the core rule fields, but confidence is still below the auto-apply threshold."
                ),
            },
            "affected_clients": affected_clients,
            "raw_excerpt": self._truncate_text(item.raw_text, 240),
        }

    def _notice_review_payload(
        self,
        notice: NoticeRecord,
        *,
        clients_by_id: dict[str, Client],
    ) -> dict[str, object]:
        impacts = self._notice_client_impacts(notice, clients_by_id=clients_by_id)
        task_count = len([impact for impact in impacts if impact["disposition"] == "task_created"])
        blocker_count = len([impact for impact in impacts if impact["disposition"] == "blocker_created"])
        return {
            "notice_id": notice.notice_id,
            "title": notice.title,
            "status": notice.status.value,
            "source": self._source_metadata_for_url(notice.source_url, fallback_label=notice.source_label),
            "source_url": notice.source_url,
            "summary": notice.summary,
            "updated_at": notice.updated_at.isoformat(),
            "interpretation": {
                "summary": notice.summary or "Official notice captured from a monitored source.",
                "outcome": f"Generated {task_count} review task(s) and {blocker_count} blocker(s).",
                "requires_cpa_decision": notice.status in {NoticeStatus.QUEUED, NoticeStatus.ESCALATED},
            },
            "affected_clients": impacts,
        }

    def _active_rule_payload(
        self,
        rule: RuleRecord,
        *,
        deadlines: list[Deadline],
        clients_by_id: dict[str, Client],
    ) -> dict[str, object]:
        matching_deadlines = [deadline for deadline in deadlines if deadline.rule_id == rule.rule_id]
        return {
            "rule_id": rule.rule_id,
            "tax_type": rule.tax_type,
            "jurisdiction": rule.jurisdiction,
            "deadline_date": rule.deadline_date,
            "effective_from": rule.effective_from,
            "status": rule.status.value,
            "confidence_score": rule.confidence_score,
            "source": self._source_metadata_for_url(rule.source_url),
            "affected_clients": [
                {
                    "client_id": deadline.client_id,
                    "client_name": clients_by_id[deadline.client_id].name if deadline.client_id in clients_by_id else None,
                    "deadline_id": deadline.deadline_id,
                    "due_date": deadline.due_date,
                    "status": deadline.status.value,
                }
                for deadline in matching_deadlines
            ],
        }

    def _notice_client_impacts(
        self,
        notice: NoticeRecord,
        *,
        clients_by_id: dict[str, Client],
    ) -> list[dict[str, object]]:
        source_prefix = f"{notice.notice_id}:"
        impacts: list[dict[str, object]] = []
        for task in self.list_tasks(notice.tenant_id, source_type="notice"):
            if not task.source_id or not task.source_id.startswith(source_prefix):
                continue
            client = clients_by_id.get(task.client_id)
            impacts.append(
                {
                    "client_id": task.client_id,
                    "client_name": client.name if client else None,
                    "disposition": "task_created",
                    "work_item_id": task.task_id,
                    "status": task.status.value,
                    "title": task.title,
                    "reason": self._reason_from_notice_description(task.description),
                }
            )
        for blocker in self.list_blockers(notice.tenant_id, source_type="notice"):
            if not blocker.source_id or not blocker.source_id.startswith(source_prefix):
                continue
            client = clients_by_id.get(blocker.client_id)
            impacts.append(
                {
                    "client_id": blocker.client_id,
                    "client_name": client.name if client else None,
                    "disposition": "blocker_created",
                    "work_item_id": blocker.blocker_id,
                    "status": blocker.status.value,
                    "title": blocker.title,
                    "reason": self._reason_from_notice_description(blocker.description),
                }
            )
        impacts.sort(key=lambda item: (str(item.get("client_name") or ""), str(item.get("disposition") or "")))
        return impacts

    def _matched_clients_for_parse_payload(
        self,
        parse_payload: dict[str, object],
        *,
        clients: list[Client],
        deadlines: list[Deadline],
    ) -> list[dict[str, object]]:
        jurisdiction = str(parse_payload.get("jurisdiction") or "").upper()
        tax_type = str(parse_payload.get("tax_type") or "").lower()
        matched: dict[str, dict[str, object]] = {}
        for deadline in deadlines:
            if jurisdiction:
                deadline_jurisdiction = deadline.jurisdiction.upper()
                if jurisdiction == "FEDERAL" and deadline_jurisdiction != "FEDERAL":
                    continue
                if jurisdiction != "FEDERAL" and deadline_jurisdiction != jurisdiction:
                    continue
            if tax_type and deadline.tax_type.lower() != tax_type:
                continue
            client = next((item for item in clients if item.client_id == deadline.client_id), None)
            matched[deadline.client_id] = {
                "client_id": deadline.client_id,
                "client_name": client.name if client else None,
                "match_reason": self._match_reason(jurisdiction=jurisdiction, tax_type=tax_type, via_deadline=True),
                "deadline_id": deadline.deadline_id,
                "due_date": deadline.due_date,
                "status": deadline.status.value,
            }
        for client in clients:
            if client.client_id in matched:
                continue
            if jurisdiction == "FEDERAL" or (jurisdiction and jurisdiction in client.registered_states):
                matched[client.client_id] = {
                    "client_id": client.client_id,
                    "client_name": client.name,
                    "match_reason": self._match_reason(jurisdiction=jurisdiction, tax_type=tax_type, via_deadline=False),
                    "deadline_id": None,
                    "due_date": None,
                    "status": "profile_match",
                }
        return sorted(matched.values(), key=lambda item: str(item.get("client_name") or ""))

    def _missing_rule_parse_fields(self, parse_payload: dict[str, object]) -> list[str]:
        required = ["tax_type", "jurisdiction", "entity_types", "deadline_date", "effective_from"]
        return [field for field in required if parse_payload.get(field) in (None, "", [])]

    def _review_summary(self, parse_payload: dict[str, object], missing_fields: list[str]) -> str:
        jurisdiction = str(parse_payload.get("jurisdiction") or "unknown jurisdiction")
        tax_type = str(parse_payload.get("tax_type") or "tax rule").replace("_", " ")
        if missing_fields:
            return f"Possible {jurisdiction} {tax_type} change; missing {', '.join(missing_fields)} before auto-apply."
        return f"Possible {jurisdiction} {tax_type} change; parsed fields are complete but confidence still needs review."

    def _match_reason(self, *, jurisdiction: str, tax_type: str, via_deadline: bool) -> str:
        pieces = []
        if jurisdiction:
            pieces.append(f"{jurisdiction} footprint")
        if tax_type:
            pieces.append(f"{tax_type.replace('_', ' ')} scope")
        if via_deadline:
            pieces.append("matching deadline")
        else:
            pieces.append("matching client profile")
        return " + ".join(pieces)

    def _source_metadata_for_url(self, source_url: str, fallback_label: str | None = None) -> dict[str, object]:
        source_host = self._normalized_host(source_url)
        for definition in official_source_registry().values():
            registry_host = self._normalized_host(definition.default_url)
            if not source_host or not registry_host:
                continue
            if source_host == registry_host or source_host.endswith(f".{registry_host}") or registry_host.endswith(f".{source_host}"):
                return {
                    "source_key": definition.source_key,
                    "display_name": fallback_label or definition.display_name,
                    "jurisdiction": definition.jurisdiction,
                    "official": definition.official,
                    "url": source_url,
                    "fetch_format": definition.fetch_format,
                    "poll_frequency_minutes": definition.poll_frequency_minutes,
                }
        return {
            "source_key": None,
            "display_name": fallback_label or source_host or "External source",
            "jurisdiction": None,
            "official": False,
            "url": source_url,
            "fetch_format": None,
            "poll_frequency_minutes": None,
        }

    def _normalized_host(self, url: str | None) -> str:
        if not url:
            return ""
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.lower().removeprefix("www.")

    def _reason_from_notice_description(self, description: str | None) -> str | None:
        if not description:
            return None
        for line in description.splitlines():
            if line.startswith("Why this needs attention:"):
                return line.split(":", 1)[1].strip()
        return self._truncate_text(description, 180)

    def _truncate_text(self, text: str | None, limit: int) -> str:
        if not text:
            return ""
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: max(0, limit - 1)].rstrip()}…"

    def _find_open_task_for_notice_client(self, tenant_id: str, client_id: str, source_id: str) -> Task | None:
        return self._find_open_task_for_source(tenant_id, client_id, "notice", source_id)

    def _find_open_task_for_source(
        self,
        tenant_id: str,
        client_id: str,
        source_type: str,
        source_id: str,
    ) -> Task | None:
        with self._connect(tenant_id=tenant_id) as conn:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE tenant_id = ? AND client_id = ? AND source_type = ? AND source_id = ?
                  AND status NOT IN (?, ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (tenant_id, client_id, source_type, source_id, TaskStatus.DONE.value, TaskStatus.DISMISSED.value),
            ).fetchone()
        return self._task_from_row(dict(row)) if row else None

    def _find_open_blocker_for_notice_client(self, tenant_id: str, client_id: str, source_id: str) -> Blocker | None:
        with self._connect(tenant_id=tenant_id) as conn:
            row = conn.execute(
                """
                SELECT * FROM blockers
                WHERE tenant_id = ? AND client_id = ? AND source_type = 'notice' AND source_id = ?
                  AND status NOT IN (?, ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (tenant_id, client_id, source_id, BlockerStatus.RESOLVED.value, BlockerStatus.DISMISSED.value),
            ).fetchone()
        return self._blocker_from_row(dict(row)) if row else None

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

    def _notification_route_from_row(self, row: dict) -> NotificationRoute:
        return NotificationRoute(
            route_id=row["route_id"],
            tenant_id=row["tenant_id"],
            channel=NotificationChannel(row["channel"]),
            destination=row["destination"],
            enabled=bool(row["enabled"]),
            created_at=self._parse_datetime(row["created_at"]),
        )

    def _notification_delivery_from_row(self, row: dict) -> NotificationDelivery:
        return NotificationDelivery(
            delivery_id=row["delivery_id"],
            tenant_id=row["tenant_id"],
            client_id=row["client_id"],
            deadline_id=row["deadline_id"],
            reminder_id=row["reminder_id"],
            channel=NotificationChannel(row["channel"]),
            destination=row["destination"],
            subject=row["subject"],
            body=row["body"],
            status=NotificationStatus(row["status"]),
            provider_message_id=row["provider_message_id"],
            error_message=row["error_message"],
            created_at=self._parse_datetime(row["created_at"]),
            sent_at=self._parse_datetime(row["sent_at"]) if row["sent_at"] else None,
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
