from __future__ import annotations

from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from ..config import BASE_DIR


def tenant_data_dir(tenant_id: str) -> Path:
    """Return the isolated data directory path for a tenant.

    Guarantees hard-path separation under ``data/tenants/{tenant_id}/``.
    """
    path = BASE_DIR / "data" / "tenants" / tenant_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def tenant_audit_log_path(tenant_id: str) -> Path:
    """Return the tenant-scoped audit log file path."""
    return tenant_data_dir(tenant_id) / "audit.log"


def assert_same_tenant(ctx_tenant_id: str, target_tenant_id: str) -> None:
    """Fail closed if an action attempts cross-tenant access."""
    if ctx_tenant_id != target_tenant_id:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: tenant '{ctx_tenant_id}' cannot access resource belonging to '{target_tenant_id}'",
        )
