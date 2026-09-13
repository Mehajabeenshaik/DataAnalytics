from __future__ import annotations

from typing import List, Optional
from .models import Tenant, TenantQuota
from .store import TenantStore


class TenantService:
    """Service layer for tenant management and resolution."""

    def __init__(self, store: Optional[TenantStore] = None) -> None:
        self.store = store or TenantStore()

    def create_tenant(
        self,
        tenant_id: str,
        name: str,
        api_keys: Optional[List[str]] = None,
        quota: Optional[TenantQuota] = None,
        status: str = "active",
    ) -> Tenant:
        tenant = Tenant(
            id=tenant_id,
            name=name,
            status=status,
            api_keys=api_keys or [f"key_{tenant_id}_default"],
            quota=quota or TenantQuota(),
        )
        return self.store.create(tenant)

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        return self.store.get(tenant_id)

    def list_tenants(self) -> List[Tenant]:
        return self.store.list_all()

    def resolve_api_key(self, api_key: str) -> Optional[Tenant]:
        return self.store.get_by_api_key(api_key)

    def seed_defaults(self) -> None:
        """Seed tenant_a, tenant_b, and default if not present."""
        if not self.get_tenant("default"):
            self.create_tenant(
                tenant_id="default",
                name="Default Demo Tenant",
                api_keys=["key_default_demo"],
            )
        if not self.get_tenant("tenant_a"):
            self.create_tenant(
                tenant_id="tenant_a",
                name="Tenant Alpha",
                api_keys=["key_tenant_a_123"],
            )
        if not self.get_tenant("tenant_b"):
            self.create_tenant(
                tenant_id="tenant_b",
                name="Tenant Beta",
                api_keys=["key_tenant_b_456"],
            )


_global_service: Optional[TenantService] = None


def get_tenant_service() -> TenantService:
    global _global_service
    if _global_service is None:
        _global_service = TenantService()
        _global_service.seed_defaults()
    return _global_service
