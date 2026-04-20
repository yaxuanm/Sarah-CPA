from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .core.bus import InMemoryEventBus
from .core.clock import SystemClock
from .core.engine import InfrastructureEngine
from .core.postgres import PostgresStorage
from .core.repositories import Repositories
from .core.storage import SQLiteStorage


@dataclass(slots=True)
class App:
    engine: InfrastructureEngine


def create_app(db_path: str | None = None) -> App:
    repositories = Repositories(storage=build_storage(db_path))
    event_bus = InMemoryEventBus()
    clock = SystemClock()
    engine = InfrastructureEngine(
        repositories=repositories,
        event_bus=event_bus,
        clock=clock,
    )
    return App(engine=engine)


def build_storage(db_path: str | None = None):
    db_path = db_path or os.getenv("DUEDATEHQ_DATABASE_URL")
    if db_path and db_path.startswith(("postgresql://", "postgres://")):
        storage = PostgresStorage(db_path)
        storage.initialize()
        return storage
    resolved = Path(db_path) if db_path else Path.cwd() / ".duedatehq" / "duedatehq.sqlite3"
    return SQLiteStorage(resolved)
