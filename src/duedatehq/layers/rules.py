from __future__ import annotations

from dataclasses import dataclass

from ..core.engine import InfrastructureEngine
from ..core.models import RuleVersion


@dataclass(slots=True)
class RuleLibraryService:
    engine: InfrastructureEngine

    def ingest_rule(self, **kwargs) -> RuleVersion:
        return self.engine.append_rule_version(**kwargs)

