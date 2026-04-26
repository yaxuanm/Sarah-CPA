from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .intent_cache import InMemoryIntentLibrary, IntentTemplate
from .storage import SQLiteStorage


class SQLiteIntentLibrary(InMemoryIntentLibrary):
    """SQLite-backed implementation of the MVP intent library interface."""

    def __init__(self, storage: SQLiteStorage, *, match_threshold: float = 0.62) -> None:
        super().__init__(match_threshold=match_threshold)
        self.storage = storage
        self._ensure_schema()
        self._templates = self._load_templates()
        self._feedback_events = self._load_feedback_events()

    def learn(self, user_input: str, plan: dict[str, Any], session: dict[str, Any], view_type: str | None = None) -> IntentTemplate:
        template = super().learn(user_input, plan, session, view_type)
        self._store_template(template)
        return template

    def record_feedback(
        self,
        intent_id: str,
        *,
        is_correction: bool,
        user_input: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().record_feedback(intent_id, is_correction=is_correction, user_input=user_input, reason=reason)
        template = self.find_by_id(intent_id)
        if template:
            self._store_template(template)
            self._insert_feedback_event(
                signal="correction" if is_correction else "success",
                intent_id=template.intent_id,
                intent_label=template.intent_label,
                user_input=user_input,
                reason=reason,
            )

    def record_missing_field(self, intent_label: str, user_input: str, reason: str | None = None) -> IntentTemplate | None:
        template = super().record_missing_field(intent_label, user_input, reason)
        if template:
            self._store_template(template)
            self._insert_feedback_event(
                signal="missing_info",
                intent_id=template.intent_id,
                intent_label=template.intent_label,
                user_input=user_input,
                reason=reason,
            )
        return template

    def feedback_events(self, *, signal: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM intent_feedback_events"
        params: list[Any] = []
        if signal:
            query += " WHERE signal = ?"
            params.append(signal)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.storage.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def review_queue(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.storage.connect() as conn:
            rows = conn.execute(
                """
                SELECT intent_id, intent_label, status, success_rate, correction_count,
                       missing_info_count, updated_at
                FROM intent_templates
                WHERE status = 'review_needed' OR correction_count > 0
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.storage.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS template_count,
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_templates,
                    SUM(CASE WHEN status = 'review_needed' THEN 1 ELSE 0 END) AS review_needed_templates
                FROM intent_templates
                """
            ).fetchone()
            events = conn.execute(
                """
                SELECT
                    COUNT(*) AS feedback_events,
                    SUM(CASE WHEN signal = 'correction' THEN 1 ELSE 0 END) AS corrections,
                    SUM(CASE WHEN signal = 'missing_info' THEN 1 ELSE 0 END) AS missing_info_events
                FROM intent_feedback_events
                """
            ).fetchone()
        return {
            "template_count": int(row["template_count"] or 0),
            "active_templates": int(row["active_templates"] or 0),
            "review_needed_templates": int(row["review_needed_templates"] or 0),
            "feedback_events": int(events["feedback_events"] or 0),
            "corrections": int(events["corrections"] or 0),
            "missing_info_events": int(events["missing_info_events"] or 0),
        }

    def _ensure_schema(self) -> None:
        with self.storage.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS intent_templates (
                    intent_id TEXT PRIMARY KEY,
                    intent_label TEXT NOT NULL UNIQUE,
                    example_inputs TEXT NOT NULL,
                    canonical_plan TEXT NOT NULL,
                    view_type TEXT NOT NULL,
                    vector TEXT NOT NULL,
                    hit_count INTEGER NOT NULL,
                    success_rate REAL NOT NULL,
                    status TEXT NOT NULL,
                    correction_count INTEGER NOT NULL DEFAULT 0,
                    missing_info_count INTEGER NOT NULL DEFAULT 0,
                    missing_info_inputs TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS intent_feedback_events (
                    feedback_id TEXT PRIMARY KEY,
                    signal TEXT NOT NULL,
                    intent_id TEXT,
                    intent_label TEXT,
                    user_input TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_template_columns(conn)

    def _ensure_template_columns(self, conn) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(intent_templates)").fetchall()}
        additions = {
            "correction_count": "INTEGER NOT NULL DEFAULT 0",
            "missing_info_count": "INTEGER NOT NULL DEFAULT 0",
            "missing_info_inputs": "TEXT NOT NULL DEFAULT '[]'",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE intent_templates ADD COLUMN {name} {definition}")

    def _load_templates(self) -> list[IntentTemplate]:
        with self.storage.connect() as conn:
            rows = conn.execute("SELECT * FROM intent_templates ORDER BY created_at").fetchall()
        return [
            IntentTemplate(
                intent_id=row["intent_id"],
                intent_label=row["intent_label"],
                example_inputs=json.loads(row["example_inputs"]),
                canonical_plan=json.loads(row["canonical_plan"]),
                view_type=row["view_type"],
                vector=json.loads(row["vector"]),
                hit_count=row["hit_count"],
                success_rate=row["success_rate"],
                status=row["status"],
                correction_count=row["correction_count"],
                missing_info_count=row["missing_info_count"],
                missing_info_inputs=json.loads(row["missing_info_inputs"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def _load_feedback_events(self) -> list[dict[str, Any]]:
        with self.storage.connect() as conn:
            rows = conn.execute("SELECT * FROM intent_feedback_events ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def _store_template(self, template: IntentTemplate) -> None:
        with self.storage.connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_templates (
                    intent_id, intent_label, example_inputs, canonical_plan, view_type, vector,
                    hit_count, success_rate, status, correction_count, missing_info_count,
                    missing_info_inputs, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(intent_id) DO UPDATE SET
                    intent_label = excluded.intent_label,
                    example_inputs = excluded.example_inputs,
                    canonical_plan = excluded.canonical_plan,
                    view_type = excluded.view_type,
                    vector = excluded.vector,
                    hit_count = excluded.hit_count,
                    success_rate = excluded.success_rate,
                    status = excluded.status,
                    correction_count = excluded.correction_count,
                    missing_info_count = excluded.missing_info_count,
                    missing_info_inputs = excluded.missing_info_inputs,
                    updated_at = excluded.updated_at
                """,
                (
                    template.intent_id,
                    template.intent_label,
                    json.dumps(template.example_inputs, ensure_ascii=False),
                    json.dumps(template.canonical_plan, ensure_ascii=False, sort_keys=True),
                    template.view_type,
                    json.dumps(template.vector, sort_keys=True),
                    template.hit_count,
                    template.success_rate,
                    template.status,
                    template.correction_count,
                    template.missing_info_count,
                    json.dumps(template.missing_info_inputs, ensure_ascii=False),
                    template.created_at.isoformat(),
                    template.updated_at.isoformat(),
                ),
            )

    def _insert_feedback_event(
        self,
        *,
        signal: str,
        intent_id: str | None,
        intent_label: str | None,
        user_input: str | None,
        reason: str | None,
    ) -> None:
        from uuid import uuid4

        now = datetime.now(timezone.utc).isoformat()
        with self.storage.connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_feedback_events (
                    feedback_id, signal, intent_id, intent_label, user_input, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"feedback-{uuid4()}", signal, intent_id, intent_label, user_input, reason, now),
            )
