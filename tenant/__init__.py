"""
Enterprise identity & isolation package.

Phase 3 of the DataAnalytics governed-agent roadmap. Provides the
org/tenant/user/membership model, a file-based tenant store, tenant-scoped
path helpers, and a CLI for admin operations.

Public API (see tenant/service.py):
    TenantService
        .create_org, .create_tenant, .add_user, .get_tenant,
        .list_tenants_for_org, .get_memberships, .require_role
"""

from .models import Org, Tenant, User, Membership, AuthContext
from .store import TenantStore
from .service import TenantService

__all__ = [
    "Org",
    "Tenant",
    "User",
    "Membership",
    "AuthContext",
    "TenantStore",
    "TenantService",
]