from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class SQLiteStorage:
    db_path: Path
    fail_next_audit_write: bool = False

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self, tenant_id: str | None = None) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    registered_states TEXT NOT NULL,
                    tax_year INTEGER NOT NULL,
                    client_type TEXT NOT NULL DEFAULT 'business',
                    legal_name TEXT,
                    home_jurisdiction TEXT,
                    primary_contact_name TEXT,
                    primary_contact_email TEXT,
                    primary_contact_phone TEXT,
                    preferred_communication_channel TEXT,
                    responsible_cpa TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
                );

                CREATE TABLE IF NOT EXISTS client_tax_profiles (
                    profile_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    tax_year INTEGER NOT NULL,
                    entity_election TEXT,
                    first_year_filing INTEGER,
                    final_year_filing INTEGER,
                    extension_requested INTEGER,
                    extension_filed INTEGER,
                    estimated_tax_required INTEGER,
                    payroll_present INTEGER,
                    contractor_reporting_required INTEGER,
                    notice_received INTEGER,
                    intake_status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (client_id, tax_year),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                    FOREIGN KEY (client_id) REFERENCES clients(client_id)
                );

                CREATE TABLE IF NOT EXISTS client_jurisdictions (
                    client_jurisdiction_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    tax_year INTEGER NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    jurisdiction_type TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (client_id, tax_year, jurisdiction, jurisdiction_type),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                    FOREIGN KEY (client_id) REFERENCES clients(client_id)
                );

                CREATE TABLE IF NOT EXISTS client_contacts (
                    contact_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT,
                    email TEXT,
                    phone TEXT,
                    preferred_channel TEXT,
                    is_primary INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                    FOREIGN KEY (client_id) REFERENCES clients(client_id)
                );

                CREATE TABLE IF NOT EXISTS rules (
                    rule_id TEXT PRIMARY KEY,
                    tax_type TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    entity_types TEXT NOT NULL,
                    deadline_date TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    superseded_by TEXT,
                    raw_text TEXT,
                    fetched_at TEXT
                );

                CREATE TABLE IF NOT EXISTS rule_review_queue (
                    review_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    parse_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fetch_runs (
                    fetch_run_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    rule_id TEXT,
                    review_id TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS job_queue (
                    job_id TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    job_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS notification_routes (
                    route_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
                );

                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    deadline_id TEXT NOT NULL,
                    reminder_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_message_id TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                    FOREIGN KEY (client_id) REFERENCES clients(client_id),
                    FOREIGN KEY (deadline_id) REFERENCES deadlines(deadline_id),
                    FOREIGN KEY (reminder_id) REFERENCES reminders(reminder_id)
                );

                CREATE TABLE IF NOT EXISTS deadlines (
                    deadline_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    tax_type TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reminder_type TEXT NOT NULL,
                    override_date TEXT,
                    snoozed_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (client_id, tax_type, jurisdiction),
                    FOREIGN KEY (client_id) REFERENCES clients(client_id),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                    FOREIGN KEY (rule_id) REFERENCES rules(rule_id)
                );

                CREATE TABLE IF NOT EXISTS deadline_transitions (
                    transition_id TEXT PRIMARY KEY,
                    deadline_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (deadline_id) REFERENCES deadlines(deadline_id),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id TEXT PRIMARY KEY,
                    deadline_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    triggered_at TEXT,
                    status TEXT NOT NULL,
                    reminder_day TEXT NOT NULL,
                    reminder_type TEXT NOT NULL,
                    responded_at TEXT,
                    response TEXT,
                    FOREIGN KEY (deadline_id) REFERENCES deadlines(deadline_id),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
                    FOREIGN KEY (client_id) REFERENCES clients(client_id)
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    log_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_ip TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS audit_log_no_update
                BEFORE UPDATE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
                BEFORE DELETE ON audit_log
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log is append-only');
                END;
                """
            )
            self._ensure_clients_columns(conn)

    @contextmanager
    def transaction(self, tenant_id: str | None = None) -> Iterator[sqlite3.Connection]:
        connection = self.connect(tenant_id=tenant_id)
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def encode_json(self, value: object) -> str:
        return json.dumps(value, sort_keys=True)

    @contextmanager
    def tenant_context(self, connection: sqlite3.Connection, tenant_id: str | None):
        yield connection

    def _ensure_clients_columns(self, conn: sqlite3.Connection) -> None:
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(clients)").fetchall()
        }
        expected_columns = {
            "client_type": "TEXT NOT NULL DEFAULT 'business'",
            "legal_name": "TEXT",
            "home_jurisdiction": "TEXT",
            "primary_contact_name": "TEXT",
            "primary_contact_email": "TEXT",
            "primary_contact_phone": "TEXT",
            "preferred_communication_channel": "TEXT",
            "responsible_cpa": "TEXT",
            "is_active": "INTEGER NOT NULL DEFAULT 1",
        }
        for column_name, column_def in expected_columns.items():
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE clients ADD COLUMN {column_name} {column_def}")
