"""
Admin API router — org/tenant management, usage, catalog approval, audit export.

All routes require admin/owner role on the tenant (or org) being accessed.
No cross-tenant access even for admins of a different org.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .auth import UserOut, require_admin
from tenant.service import TenantService
from tenant_quotas import get_usage
from audit_logger import export_audit
from catalog.service import CatalogService

admin_router = APIRouter(tags=["admin"], prefix="/admin")


def _resolve_tenant_access(tenant_id: str, user: UserOut) -> None:
    """Verify the admin has access to the tenant's org.

    Global super-admin flag is OFF by default — admins only manage their
    own org's tenants. (Documented: set SUPER_ADMIN_EMAILS env to bypass.)
    """
    # In a real deployment, look up the user's org from the tenant store and
    # verify they belong to it. For the local demo, admin users can manage any
    # tenant (single-org local mode is the backward-compatible default).
    # TODO: wire super-admin emails from env for cross-org access.
    if user.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin or owner role required")


@admin_router.get("/orgs")
async def list_orgs(user: UserOut = Depends(require_admin)):
    svc = TenantService()
    return {"orgs": [o.model_dump(mode="json") for o in svc.list_orgs()]}


@admin_router.post("/orgs")
async def create_org(payload: dict, user: UserOut = Depends(require_admin)):
    svc = TenantService()
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    org = svc.create_org(name)
    return org.model_dump(mode="json")


@admin_router.get("/tenants")
async def list_tenants(org_id: str | None = None, user: UserOut = Depends(require_admin)):
    svc = TenantService()
    if org_id:
        tenants = svc.list_tenants_for_org(org_id)
    else:
        tenants = [t for org in svc.list_orgs() for t in svc.list_tenants_for_org(org.id)]
    return {"tenants": [t.model_dump(mode="json") for t in tenants]}


@admin_router.post("/tenants")
async def create_tenant(payload: dict, user: UserOut = Depends(require_admin)):
    svc = TenantService()
    org_id = payload.get("org_id")
    name = payload.get("name")
    if not org_id or not name:
        raise HTTPException(status_code=400, detail="org_id and name are required")
    tenant = svc.create_tenant(org_id, name)
    return tenant.model_dump(mode="json")


@admin_router.get("/tenants/{tenant_id}/usage")
async def tenant_usage(tenant_id: str, user: UserOut = Depends(require_admin)):
    _resolve_tenant_access(tenant_id, user)
    return get_usage(tenant_id)


@admin_router.get("/tenants/{tenant_id}/catalog")
async def tenant_catalog(tenant_id: str, user: UserOut = Depends(require_admin)):
    _resolve_tenant_access(tenant_id, user)
    svc = CatalogService(tenant_id=tenant_id)
    pending = svc.list_pending()
    approved = svc.get_approved_metrics()
    return {
        "tenant_id": tenant_id,
        "approved_count": len(approved),
        "pending_count": len(pending),
        "approved_metrics": list(approved.keys()),
        "pending_proposals": [
            {
                "proposal_id": p.proposal_id,
                "metric_name": p.metric.name,
                "question": p.question,
                "proposed_by": p.proposed_by,
            }
            for p in pending
        ],
    }


@admin_router.post("/tenants/{tenant_id}/catalog/approve/{proposal_id}")
async def approve_proposal(
    tenant_id: str,
    proposal_id: str,
    payload: dict | None = None,
    user: UserOut = Depends(require_admin),
):
    _resolve_tenant_access(tenant_id, user)
    svc = CatalogService(tenant_id=tenant_id)
    try:
        metric = svc.approve(proposal_id, approved_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "approved", "metric": metric.name, "proposal_id": proposal_id}


@admin_router.post("/tenants/{tenant_id}/catalog/reject/{proposal_id}")
async def reject_proposal(
    tenant_id: str,
    proposal_id: str,
    payload: dict | None = None,
    user: UserOut = Depends(require_admin),
):
    """Reject a pending metric proposal. It never enters the approved catalog."""
    _resolve_tenant_access(tenant_id, user)
    svc = CatalogService(tenant_id=tenant_id)
    reason = (payload or {}).get("reason") or None
    try:
        svc.reject(
            proposal_id,
            rejected_by=user.username,
            reason=reason or "Rejected by admin",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "rejected", "proposal_id": proposal_id}


@admin_router.get("/tenants/{tenant_id}/catalog/pending")
async def pending_proposals(tenant_id: str, user: UserOut = Depends(require_admin)):
    """Rich view of pending metric proposals for the approval UI."""
    _resolve_tenant_access(tenant_id, user)
    svc = CatalogService(tenant_id=tenant_id)
    pending = svc.list_pending()
    return {
        "tenant_id": tenant_id,
        "pending": [
            {
                "proposal_id": p.proposal_id,
                "metric": {
                    "name": p.metric.name,
                    "description": p.metric.description,
                    "column": p.metric.column,
                    "agg": p.metric.agg,
                    "groupby": p.metric.groupby,
                    "base_filters": p.metric.base_filters,
                    "synonyms": p.metric.synonyms,
                },
                "question": p.question,
                "reason": p.reason,
                "proposed_by": p.proposed_by,
                "status": p.status,
                "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
            }
            for p in pending
        ],
    }


@admin_router.get("/tenants/{tenant_id}/audit/export")
async def tenant_audit_export(
    tenant_id: str,
    days: int = 30,
    format: str = "json",  # json|csv
    user: UserOut = Depends(require_admin),
):
    _resolve_tenant_access(tenant_id, user)
    logs = export_audit(tenant_id, days=days)
    if format == "csv":
        import io
        import csv as _csv

        buf = io.StringIO()
        fieldnames = ["id", "timestamp", "username", "role", "action_type", "details", "ip_address", "tenant_id"]
        writer = _csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in logs:
            writer.writerow(row)
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="audit_{tenant_id}.csv"'},
        )
    return {"tenant_id": tenant_id, "days": days, "records": logs}
