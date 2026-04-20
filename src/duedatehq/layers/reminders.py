from __future__ import annotations

from dataclasses import dataclass

from ..core.engine import InfrastructureEngine
from ..core.models import Deadline, DeadlineStatus


@dataclass(slots=True)
class ReminderService:
    engine: InfrastructureEngine

    def mark_completed(self, tenant_id: str, deadline_id: str, actor_id: str, reason: str = "user_completed") -> Deadline:
        return self.engine.transition_deadline_status(tenant_id, deadline_id, DeadlineStatus.COMPLETED, actor_id, reason)

