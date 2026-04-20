from __future__ import annotations

from dataclasses import dataclass

from ..core.engine import InfrastructureEngine


@dataclass(slots=True)
class AuditService:
    engine: InfrastructureEngine

