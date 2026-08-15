from __future__ import annotations
import os

def get_sso_provider():
    name = (os.getenv("SSO_PROVIDER") or "local").strip().lower()
    if name == "local":
        from .local import LocalSSOProvider
        return LocalSSOProvider()
    from .local import LocalSSOProvider
    return LocalSSOProvider()
</write_to_file>
<write_to_file>
<path>auth_sso_routes.py</path>
<content>
from __future__ import annotations
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from sso.factory import get_sso_provider

sso_router = APIRouter(prefix="/auth/sso", tags=["sso"])

@sso_router.post("/local")
def sso_local(payload: dict):
    provider = get_sso_provider()
    try:
        sso_user = provider.handle_callback(payload or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tenant_id = (payload or {}).get("tenant_id")
    roles = (payload or {}).get("roles") or ["admin"]
    if isinstance(roles, str):
        roles = [roles]

    token_data = {
        "sub": sso_user.email,
        "email": sso_user.email,
        "tenant_id": tenant_id,
        "roles": roles,
    }

    try:
        from auth import create_access_token
        token = create_access_token(token_data)
    except Exception:
        from jose import jwt
        from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES
        to_encode = dict(token_data)
        to_encode["exp"] = datetime.utcnow() + timedelta(minutes=int(JWT_EXPIRE_MINUTES))
        token = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    return {
        "access_token": token,
        "token_type": "bearer",
        "email": sso_user.email,
        "tenant_id": tenant_id,
        "roles": roles,
    }