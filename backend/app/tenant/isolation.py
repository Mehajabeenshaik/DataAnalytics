"""
Tenant isolation helpers.

Guarantee that every tenant-scoped resource (catalog, data, audit, cache
keys) is namespaced by tenant_id so no cross-tenant leakage is possible by
construction.
"""

from __future__ import annotations

from pathlib import Path

from config import BASE_DIR


def catalog_root(tenant_id: str) -> Path:
    """Return the tenant-scoped catalog root: data/catalog/<tenant_id>/."""
    return Path(BASE_DIR) / "data" / "catalog" / tenant_id


def tenant_data_root(tenant_id: str) -> Path:
    """Return the tenant-scoped data root: data/tenants_data/<tenant_id>/."""
    return Path(BASE_DIR) / "data" / "tenants_data" / tenant_id


def audit_scope(tenant_id: str) -> str:
    """Return the tenant_id used to scope audit records (identity-safe)."""
    return tenant_id


def cache_namespace(tenant_id: str) -> str:
    """Return a cache-key namespace prefix for a tenant."""
    return f"tenant:{tenant_id}"


def require_tenant_context(tenant_id: str | None) -> str:
    """Hard-fail if no valid tenant context is present.

    Never falls back to a global catalog. Raises PermissionError (mapped to
    401/403 by the API layer) when tenant_id is missing or empty.
    """
    if not tenant_id or not str(tenant_id).strip():
        raise PermissionError("Missing tenant context — refusing to operate without tenant isolation.")
    return str(tenant_id).strip()