from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from .engine import InfrastructureEngine
from .fetchers import Fetcher


@dataclass(slots=True)
class QueuedJob:
    job_id: str
    tenant_id: str | None
    job_type: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    available_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None


class JobQueue(Protocol):
    def enqueue(self, job_type: str, payload: dict[str, Any], created_at: datetime, tenant_id: str | None = None, available_at: datetime | None = None) -> QueuedJob: ...
    def drain(self, job_type: str | None = None, tenant_id: str | None = None, now: datetime | None = None) -> list[QueuedJob]: ...


@dataclass(slots=True)
class InMemoryJobQueue:
    jobs: list[QueuedJob] = field(default_factory=list)

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        created_at: datetime,
        tenant_id: str | None = None,
        available_at: datetime | None = None,
    ) -> QueuedJob:
        job = QueuedJob(
            job_id=str(uuid4()),
            tenant_id=tenant_id,
            job_type=job_type,
            payload=payload,
            status="queued",
            created_at=created_at,
            available_at=available_at or created_at,
        )
        self.jobs.append(job)
        return job

    def drain(self, job_type: str | None = None, tenant_id: str | None = None, now: datetime | None = None) -> list[QueuedJob]:
        now = now or datetime.utcnow()
        selected = [
            job
            for job in self.jobs
            if (job_type is None or job.job_type == job_type)
            and (tenant_id is None or job.tenant_id == tenant_id)
            and job.available_at <= now
        ]
        self.jobs = [job for job in self.jobs if job not in selected]
        return selected


@dataclass(slots=True)
class PersistentJobQueue:
    storage: object

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        created_at: datetime,
        tenant_id: str | None = None,
        available_at: datetime | None = None,
    ) -> QueuedJob:
        job = QueuedJob(
            job_id=str(uuid4()),
            tenant_id=tenant_id,
            job_type=job_type,
            payload=payload,
            status="queued",
            created_at=created_at,
            available_at=available_at or created_at,
        )
        with self.storage.transaction(tenant_id=tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO job_queue (
                    job_id, tenant_id, job_type, payload, status, created_at, available_at, claimed_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    job.job_id,
                    job.tenant_id,
                    job.job_type,
                    self.storage.encode_json(job.payload),
                    job.status,
                    job.created_at.isoformat(),
                    job.available_at.isoformat(),
                ),
            )
        return job

    def drain(self, job_type: str | None = None, tenant_id: str | None = None, now: datetime | None = None) -> list[QueuedJob]:
        now = now or datetime.utcnow()
        query = "SELECT * FROM job_queue WHERE status = ? AND available_at <= ?"
        params: list[object] = ["queued", now.isoformat()]
        if job_type:
            query += " AND job_type = ?"
            params.append(job_type)
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        query += " ORDER BY created_at"
        with self.storage.transaction(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, params).fetchall()
            jobs = [self._job_from_row(dict(row)) for row in rows]
            for job in jobs:
                conn.execute(
                    "UPDATE job_queue SET status = ?, claimed_at = ? WHERE job_id = ?",
                    ("claimed", now.isoformat(), job.job_id),
                )
        return [
            QueuedJob(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                job_type=job.job_type,
                payload=job.payload,
                status="claimed",
                created_at=job.created_at,
                available_at=job.available_at,
                claimed_at=now,
                completed_at=None,
            )
            for job in jobs
        ]

    def complete(self, jobs: list[QueuedJob], now: datetime) -> None:
        if not jobs:
            return
        tenant_id = jobs[0].tenant_id
        with self.storage.transaction(tenant_id=tenant_id) as conn:
            for job in jobs:
                conn.execute(
                    "UPDATE job_queue SET status = ?, completed_at = ? WHERE job_id = ?",
                    ("completed", now.isoformat(), job.job_id),
                )

    def list_jobs(self, tenant_id: str | None = None) -> list[QueuedJob]:
        query = "SELECT * FROM job_queue ORDER BY created_at"
        params: list[object] = []
        if tenant_id:
            query = "SELECT * FROM job_queue WHERE tenant_id = ? ORDER BY created_at"
            params.append(tenant_id)
        with self.storage.connect(tenant_id=tenant_id) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._job_from_row(dict(row)) for row in rows]

    def _job_from_row(self, row: dict[str, Any]) -> QueuedJob:
        return QueuedJob(
            job_id=row["job_id"],
            tenant_id=row["tenant_id"],
            job_type=row["job_type"],
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            status=row["status"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            available_at=datetime.fromisoformat(str(row["available_at"])),
            claimed_at=datetime.fromisoformat(str(row["claimed_at"])) if row["claimed_at"] else None,
            completed_at=datetime.fromisoformat(str(row["completed_at"])) if row["completed_at"] else None,
        )


@dataclass(slots=True)
class ReminderScheduler:
    engine: InfrastructureEngine
    queue: JobQueue

    def enqueue_next_window(self, tenant_id: str, now: datetime, hours: int = 24) -> list[QueuedJob]:
        cutoff = now + timedelta(hours=hours)
        reminders = [
            reminder
            for reminder in self.engine.list_reminders(tenant_id)
            if reminder.status.value == "scheduled" and now <= reminder.scheduled_at <= cutoff
        ]
        return [
            self.queue.enqueue(
                "send_reminder",
                {"tenant_id": reminder.tenant_id, "deadline_id": reminder.deadline_id, "reminder_id": reminder.reminder_id},
                created_at=now,
                tenant_id=tenant_id,
                available_at=reminder.scheduled_at,
            )
            for reminder in reminders
        ]


@dataclass(slots=True)
class ReminderWorker:
    engine: InfrastructureEngine
    queue: PersistentJobQueue | InMemoryJobQueue | None = None

    def run(self, queued_jobs: list[QueuedJob], now: datetime) -> int:
        if not queued_jobs:
            return 0
        dispatched = self.engine.trigger_due_reminders(now)
        if self.queue and hasattr(self.queue, "complete"):
            self.queue.complete(queued_jobs, now)
        return dispatched


@dataclass(slots=True)
class FetchWorker:
    engine: InfrastructureEngine

    def run(
        self,
        *,
        source: str | None = None,
        state: str | None = None,
        fetcher: Fetcher,
        actor: str = "worker",
    ) -> dict[str, object]:
        document = fetcher.fetch()
        return self.engine.fetch_from_source(
            source=source,
            state=state,
            raw_text=document.raw_text,
            source_url=document.source_url,
            fetched_at=document.fetched_at,
            actor=actor,
        )
