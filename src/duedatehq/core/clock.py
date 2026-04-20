from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(slots=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

