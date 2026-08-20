from __future__ import annotations
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from sso.factory import get_sso_provider

sso_router = APIRouter(prefix="/auth/sso", tags=["sso"])


def _issue_token(email: str, tenant_id: str | None, roles: list[str]) -> str:
    token_data = {
        "sub": email,
        "email": email,
        "tenant_id": tenant_id,
        "roles": roles,
    }
    try:
        from .auth import create_access_token
        return create_access_token(token_data)
    except Exception:
        from jose import jwt
        from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES
        to_encode = dict(token_data)
        to_encode["exp"] = datetime.utcnow() + timedelta(minutes=int(JWT_EXPIRE_MINUTES))
        return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


@sso_router.post("/local")
def sso_local(payload: dict):
    """Dev/local SSO. Production path uses OIDC stubs when OIDC_ENABLED=true."""
    provider = get_sso_provider()
    try:
        sso_user = provider.handle_callback(payload or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tenant_id = (payload or {}).get("tenant_id")
    roles = (payload or {}).get("roles") or ["analyst"]
    if isinstance(roles, str):
        roles = [roles]

    # Best-effort link to tenant identity layer
    try:
        from tenant.service import TenantService
        svc = TenantService()
        user = None
        if hasattr(svc, "ensure_user"):
            user = svc.ensure_user(email=sso_user.email, name=sso_user.name)
        if user is not None and hasattr(svc, "list_memberships_for_user"):
            memberships = svc.list_memberships_for_user(user.id)
            if not tenant_id:
                if len(memberships) == 1:
                    tenant_id = memberships[0].tenant_id
                    roles = [memberships[0].role] if memberships[0].role else roles
                elif len(memberships) > 1:
                    return {
                        "need_tenant_choice": True,
                        "tenants": [
                            {"tenant_id": m.tenant_id, "role": m.role}
                            for m in memberships
                        ],
                    }
            else:
                allowed = {m.tenant_id: m for m in memberships}
                if memberships and tenant_id not in allowed:
                    raise HTTPException(status_code=403, detail="not a member of tenant")
                if tenant_id in allowed:
                    roles = [allowed[tenant_id].role]
    except HTTPException:
        raise
    except Exception:
        # Tenant service optional in minimal installs
        pass

    token = _issue_token(sso_user.email, tenant_id, roles)
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": sso_user.email,
        "tenant_id": tenant_id,
        "roles": roles,
    }