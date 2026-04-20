from __future__ import annotations

from dataclasses import dataclass


class TenantScopeError(PermissionError):
    pass


@dataclass(slots=True)
class TenantGuard:
    def require(self, tenant_id: str | None) -> str:
        if not tenant_id:
            raise TenantScopeError("tenant_id is required")
        return tenant_id

