from __future__ import annotations

from dataclasses import dataclass

from ..core.engine import InfrastructureEngine
from ..core.models import Client, Deadline


@dataclass(slots=True)
class ClientRuleMappingService:
    engine: InfrastructureEngine

    def register_client(
        self,
        tenant_id: str,
        name: str,
        entity_type: str,
        registered_states: list[str],
        tax_year: int,
        **kwargs,
    ) -> Client:
        return self.engine.register_client(
            tenant_id=tenant_id,
            name=name,
            entity_type=entity_type,
            registered_states=registered_states,
            tax_year=tax_year,
            **kwargs,
        )

    def create_deadline(self, tenant_id: str, client_id: str, source_rule_id: str, tax_type: str, due_date: str) -> Deadline:
        return self.engine.create_deadline(tenant_id, client_id, source_rule_id, tax_type, due_date)
