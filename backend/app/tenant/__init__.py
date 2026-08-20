"""
Enterprise identity & isolation package.

Phase 3 of the DataAnalytics governed-agent roadmap. Provides the
org/tenant/user/membership model, a pluggable tenant store (file-based by
default; Postgres when TENANT_STORE=postgres), tenant-scoped path helpers,
and a CLI for admin operations.

Public API (see tenant/service.py):
    TenantService
        .create_org, .create_tenant, .add_user, .get_tenant,
        .list_tenants_for_org, .get_memberships, .require_role

Store selection (see tenant/store.py):
    get_store()   → returns FileTenantStore or PostgresTenantStore per config
    TenantStore   → alias for FileTenantStore (backward compat)

Widget API-key management (see tenant/widget_keys.py):
    WidgetTenant           → lightweight tenant dataclass for X-API-Key auth
    init_tenant_db()       → ensure tenants table + demo row exist
    create_api_key(...)    → generate and persist a new widget API key
    validate_api_key(key)  → return WidgetTenant | None
    list_tenants()         → list all active WidgetTenants
    revoke_api_key(key)    → soft-delete (set is_active=0)

Note on naming: The enterprise Tenant model (tenant/models.py) is the full
org/user identity record. WidgetTenant (tenant/widget_keys.py) is the
simpler per-company API-key record used by the embeddable widget. Both are
exported here. api_widget.py type-annotates with the bare name `Tenant` —
it refers to WidgetTenant, imported below via the alias.
"""

from .models import Org, Tenant, User, Membership, AuthContext
from .store import TenantStore, FileTenantStore, get_store
from .service import TenantService
from .widget_keys import (
    WidgetTenant,
    init_tenant_db,
    create_api_key,
    validate_api_key,
    list_tenants,
    revoke_api_key,
)

__all__ = [
    # Enterprise identity
    "Org",
    "Tenant",
    "User",
    "Membership",
    "AuthContext",
    "TenantStore",
    "FileTenantStore",
    "TenantService",
    "get_store",
    # Widget API-key management
    "WidgetTenant",
    "init_tenant_db",
    "create_api_key",
    "validate_api_key",
    "list_tenants",
    "revoke_api_key",
]