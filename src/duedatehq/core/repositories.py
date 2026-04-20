from __future__ import annotations

from dataclasses import dataclass

from .storage import SQLiteStorage


@dataclass(slots=True)
class Repositories:
    storage: SQLiteStorage
