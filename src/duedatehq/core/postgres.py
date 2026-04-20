from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import uuid4


class PostgresCursorAdapter:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgresConnectionAdapter:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, query: str, params=None):
        with self._connection.cursor() as cur:
            cur.execute(_translate_query(query), params or ())
            if cur.description is None:
                return PostgresCursorAdapter(cur)
            rows = cur.fetchall()
        return InMemoryRowsAdapter(rows)

    def cursor(self):
        return self._connection.cursor()

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class InMemoryRowsAdapter:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


@dataclass(slots=True)
class PostgresStorage:
    dsn: str
    schema_path: Path | None = None
    fail_next_audit_write: bool = False

    def __post_init__(self) -> None:
        self._psycopg = self._import_driver()
        self.schema_path = self.schema_path or Path(__file__).resolve().parents[3] / "db" / "postgres_schema.sql"

    def _import_driver(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL support requires psycopg. Install it before using a postgres DSN."
            ) from exc
        return psycopg

    def connect(self, tenant_id: str | None = None):
        connection = self._psycopg.connect(self.dsn, row_factory=self._psycopg.rows.dict_row)
        if tenant_id is not None:
            self._set_tenant(connection, tenant_id)
        return PostgresConnectionAdapter(connection)

    def raw_connect(self):
        return self._psycopg.connect(self.dsn, row_factory=self._psycopg.rows.dict_row)

    def initialize(self) -> None:
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        raw_connection = self._psycopg.connect(self.dsn, row_factory=self._psycopg.rows.dict_row)
        with raw_connection as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()

    @contextmanager
    def transaction(self, tenant_id: str | None = None) -> Iterator[object]:
        connection = self.connect(tenant_id=tenant_id)
        try:
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
    def tenant_context(self, connection, tenant_id: str | None):
        previous = None
        if tenant_id is not None:
            with connection.cursor() as cur:
                cur.execute("SELECT current_setting('app.tenant_id', true)")
                row = cur.fetchone()
                previous = row[0] if row else None
            self._set_tenant(connection, tenant_id)
        try:
            yield connection
        finally:
            if tenant_id is not None:
                with connection.cursor() as cur:
                    if previous:
                        cur.execute("SET app.tenant_id = %s", (previous,))
                    else:
                        cur.execute("RESET app.tenant_id")

    def _set_tenant(self, connection, tenant_id: str) -> None:
        raw_connection = getattr(connection, "_connection", connection)
        with raw_connection.cursor() as cur:
            cur.execute("SET app.tenant_id = %s", (tenant_id,))

    def healthcheck(self) -> dict[str, object]:
        with self.raw_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version(), current_setting('app.tenant_id', true)")
                row = cur.fetchone()
        return {
            "database": "postgresql",
            "version": row[0],
            "tenant_id": row[1],
        }

    def run_rls_self_test(self) -> dict[str, object]:
        tenant_a = f"tenant_rls_a_{uuid4().hex[:8]}"
        tenant_b = f"tenant_rls_b_{uuid4().hex[:8]}"
        client_a = f"client_rls_a_{uuid4().hex[:8]}"
        client_b = f"client_rls_b_{uuid4().hex[:8]}"
        with self.raw_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO duedatehq, public")
                cur.execute(
                    "INSERT INTO tenants (tenant_id, name, created_at, is_deleted) VALUES (%s, %s, now(), false), (%s, %s, now(), false)",
                    (tenant_a, "Tenant A", tenant_b, "Tenant B"),
                )
                cur.execute(
                    """
                    INSERT INTO clients (client_id, tenant_id, name, entity_type, registered_states, tax_year, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, 2026, now(), now()),
                           (%s, %s, %s, %s, %s::jsonb, 2026, now(), now())
                    """,
                    (
                        client_a,
                        tenant_a,
                        "Client A",
                        "s-corp",
                        '["CA"]',
                        client_b,
                        tenant_b,
                        "Client B",
                        "s-corp",
                        '["NY"]',
                    ),
                )
                cur.execute("SET app.tenant_id = %s", (tenant_a,))
                cur.execute("SELECT count(*) FROM clients")
                visible_count = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM clients WHERE tenant_id = %s", (tenant_b,))
                cross_tenant_visible = cur.fetchone()[0]
                cur.execute("RESET app.tenant_id")
                require_error = None
                try:
                    cur.execute("SELECT duedatehq.require_tenant_id()")
                    cur.fetchone()
                except Exception as exc:
                    require_error = str(exc)
                cur.execute("DELETE FROM clients WHERE client_id IN (%s, %s)", (client_a, client_b))
                cur.execute("DELETE FROM tenants WHERE tenant_id IN (%s, %s)", (tenant_a, tenant_b))
            conn.commit()
        return {
            "tenant_visible_rows": visible_count,
            "cross_tenant_rows": cross_tenant_visible,
            "missing_tenant_error": require_error,
        }


def _translate_query(query: str) -> str:
    return query.replace("?", "%s")
