from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class InMemoryInteractionSessionManager:
    """Small MVP session store with the same contract Redis will use later."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def start(self, tenant_id: str, *, today: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        session = {
            "session_id": session_id or str(uuid4()),
            "tenant_id": tenant_id,
            "today": today or datetime.now(timezone.utc).date().isoformat(),
            "history_window": [],
            "selectable_items": [],
            "current_view": None,
            "state_summary": None,
        }
        self._sessions[session["session_id"]] = session
        return session

    def get(self, session_id: str) -> dict[str, Any]:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"session not found: {session_id}") from exc

    def save(self, session: dict[str, Any]) -> None:
        self._sessions[session["session_id"]] = session


class RedisInteractionSessionManager:
    """Redis-backed session store with the same interface as the memory MVP."""

    def __init__(self, redis_url: str, *, ttl_seconds: int = 3600, client: Any | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        if client is not None:
            self.client = client
        else:
            try:
                import redis
            except ImportError as exc:  # pragma: no cover - optional dependency guard.
                raise RuntimeError("Redis sessions require installing the redis package.") from exc
            self.client = redis.from_url(redis_url)

    def start(self, tenant_id: str, *, today: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        session = {
            "session_id": session_id or str(uuid4()),
            "tenant_id": tenant_id,
            "today": today or datetime.now(timezone.utc).date().isoformat(),
            "history_window": [],
            "selectable_items": [],
            "current_view": None,
            "state_summary": None,
        }
        self.save(session)
        return session

    def get(self, session_id: str) -> dict[str, Any]:
        raw = self.client.get(self._key(session_id))
        if raw is None:
            raise KeyError(f"session not found: {session_id}")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def save(self, session: dict[str, Any]) -> None:
        self.client.setex(
            self._key(session["session_id"]),
            self.ttl_seconds,
            json.dumps(session, ensure_ascii=False, default=str),
        )

    def _key(self, session_id: str) -> str:
        return f"duedatehq:session:{session_id}"
