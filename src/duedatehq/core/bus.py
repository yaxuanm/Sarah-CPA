from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .events import Event


class EventHandler(Protocol):
    def handle(self, event: Event) -> None: ...


@dataclass(slots=True)
class InMemoryEventBus:
    events: list[Event] = field(default_factory=list)
    handlers: list[EventHandler] = field(default_factory=list)

    def publish(self, event: Event) -> None:
        self.events.append(event)
        for handler in list(self.handlers):
            handler.handle(event)

    def register(self, handler: EventHandler) -> None:
        self.handlers.append(handler)

