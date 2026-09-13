from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
import jwt

from .config import (
    CORE_INVARIANT,
    LOG_LEVEL,
    LLM_PROVIDER,
    TENANT_ISOLATION_ENABLED,
    DEFAULT_TENANT_ID,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
)
from .data_source import DataSource
from .metric_factory import seed_metrics
from .catalog.service import CatalogService
from .agent_phase4 import run_question_phase4
from .audit_logger import get_recent
from .tenant import get_tenant_service, TenantContext, tenant_data_dir, TenantQuota
from .tenant_quotas import get_quota_tracker
from .policy import get_confirmation_manager

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("daana")

app = FastAPI(
    title="DaAna — Phase 4 Policy & Safety",
    description=CORE_INVARIANT,
    version="0.4.0",
)

# Initialise services
tenant_service = get_tenant_service()
catalog_service = CatalogService()

# Seed default metrics for standard seed tenants
for tid in ["default", "tenant_a", "tenant_b"]:
    for metric in seed_metrics(tenant_id=tid):
        from .catalog.store import set as _store_set
        _store_set(metric)

# Tenant DataSources cache
_data_sources: dict[str, DataSource] = {}


def get_tenant_data_source(tenant_id: str) -> DataSource:
    if tenant_id not in _data_sources:
        ds = DataSource(name=f"ds_{tenant_id}", tenant_id=tenant_id)
        # Check tenant directory first, fallback to shared test fixture
        t_csv = tenant_data_dir(tenant_id) / "sample.csv"
        fixture_path = Path(__file__).parent.parent / "tests" / "fixtures" / "sample.csv"
        if t_csv.exists():
            ds.load_csv(t_csv)
        elif fixture_path.exists():
            ds.load_csv(fixture_path)
        else:
            logger.warning("No sample CSV fixture found for tenant: %s", tenant_id)
        _data_sources[tenant_id] = ds
    return _data_sources[tenant_id]


def get_current_tenant(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> TenantContext:
    """Resolve TenantContext for protected routes."""
    tenant = None
    auth_method = "demo"
    api_key_used = None

    # 1. API key resolution
    if x_api_key:
        tenant = tenant_service.resolve_api_key(x_api_key)
        if tenant:
            auth_method = "api_key"
            api_key_used = x_api_key
        else:
            raise HTTPException(status_code=401, detail="Invalid X-API-Key")

    # 2. JWT resolution
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            tenant_id = payload.get("tenant_id")
            if tenant_id:
                tenant = tenant_service.get_tenant(tenant_id)
                if tenant:
                    auth_method = "jwt"
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Invalid JWT token")

    # 3. Fallback when isolation disabled
    if tenant is None:
        if not TENANT_ISOLATION_ENABLED:
            tenant = tenant_service.get_tenant(DEFAULT_TENANT_ID)
            if tenant is None:
                tenant = tenant_service.create_tenant(DEFAULT_TENANT_ID, "Default Demo Tenant")
            auth_method = "demo"
        else:
            raise HTTPException(
                status_code=401,
                detail="Authentication required: missing or invalid X-API-Key / Authorization header",
            )

    if tenant.status == "suspended":
        raise HTTPException(status_code=403, detail=f"Tenant account '{tenant.id}' is suspended")

    return TenantContext(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        api_key_used=api_key_used,
        auth_method=auth_method,
        quota=tenant.quota,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "phase": 4,
        "tenant_isolation_enabled": TENANT_ISOLATION_ENABLED,
        "invariant": CORE_INVARIANT,
        "llm_provider": LLM_PROVIDER,
    }


@app.get("/")
def root():
    return JSONResponse(
        {
            "service": "DaAna",
            "phase": "4 — Agentic Policy & Astra Patterns",
            "message": CORE_INVARIANT,
        }
    )


@app.get("/metrics")
def list_metrics(ctx: TenantContext = Depends(get_current_tenant)):
    approved = catalog_service.list_approved(tenant_id=ctx.tenant_id)
    return [
        {
            "name": m.name,
            "description": m.description,
            "synonyms": m.synonyms,
            "tenant_id": m.tenant_id,
        }
        for m in approved
    ]


@app.post("/ask")
def ask(payload: dict, ctx: TenantContext = Depends(get_current_tenant)):
    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="'question' field required")

    # Enforce per-tenant query quota
    quota_tracker = get_quota_tracker()
    quota_tracker.check_and_increment_query(ctx.tenant_id, ctx.quota)

    ds = get_tenant_data_source(ctx.tenant_id)
    response = run_question_phase4(question, ds, catalog_service, tenant_id=ctx.tenant_id)
    return response


@app.post("/ask/confirm")
def confirm_ask(payload: dict, ctx: TenantContext = Depends(get_current_tenant)):
    token = payload.get("confirmation_token")
    approve = payload.get("approve", True)
    if not token:
        raise HTTPException(status_code=400, detail="'confirmation_token' field required")

    conf_manager = get_confirmation_manager()
    pending = conf_manager.get_pending(token)
    if not pending:
        raise HTTPException(status_code=404, detail="Confirmation token not found or expired")

    if pending.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="Confirmation token belongs to another tenant")

    resolved = conf_manager.resolve(token, approve=approve)
    if not approve:
        return {
            "status": "cancelled",
            "confirmation_token": token,
            "action_type": resolved.action_type if resolved else "unknown",
            "user_message": "Action confirmation rejected by user.",
        }

    return {
        "status": "confirmed_and_executed",
        "confirmation_token": token,
        "action_type": resolved.action_type if resolved else "unknown",
        "user_message": f"Action '{resolved.action_type if resolved else 'consequential'}' confirmed and executed successfully.",
        "tenant_id": ctx.tenant_id,
    }


@app.get("/audit/recent")
def recent_audit(limit: int = 20, ctx: TenantContext = Depends(get_current_tenant)):
    return get_recent(limit=limit, tenant_id=ctx.tenant_id)


@app.get("/tenants/me")
def tenant_me(ctx: TenantContext = Depends(get_current_tenant)):
    tenant = tenant_service.get_tenant(ctx.tenant_id)
    usage = get_quota_tracker().get_usage(ctx.tenant_id)
    return {
        "tenant": tenant,
        "usage": usage,
        "context": ctx,
    }


@app.post("/tenants")
def create_tenant(payload: dict, ctx: TenantContext = Depends(get_current_tenant)):
    tenant_id = payload.get("id")
    name = payload.get("name")
    if not tenant_id or not name:
        raise HTTPException(status_code=400, detail="'id' and 'name' fields are required")

    if tenant_service.get_tenant(tenant_id):
        raise HTTPException(status_code=409, detail=f"Tenant '{tenant_id}' already exists")

    api_keys = payload.get("api_keys") or [f"key_{tenant_id}_123"]
    quota_data = payload.get("quota")
    quota = TenantQuota(**quota_data) if quota_data else TenantQuota()

    tenant = tenant_service.create_tenant(
        tenant_id=tenant_id,
        name=name,
        api_keys=api_keys,
        quota=quota,
    )
    for metric in seed_metrics(tenant_id=tenant_id):
        from .catalog.store import set as _store_set
        _store_set(metric)

    return tenant


logger.info("DaAna Phase 4 Agentic Policy started (isolation enabled=%s). Invariant: %s", TENANT_ISOLATION_ENABLED, CORE_INVARIANT)
