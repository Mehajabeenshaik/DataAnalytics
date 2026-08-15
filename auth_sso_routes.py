from fastapi import APIRouter, Depends, HTTPException
from sso.local import LocalSSOProvider, SSOUser

router = APIRouter(prefix="/auth/sso", tags=["sso"])


@router.post("/local")
async def local_sso_login(
    email: str,
    name: str = "",
    tenant_id: str = "",
    roles: list = [],
    provider: LocalSSOProvider = Depends(get_sso_provider),
):
    user = provider.handle_callback({"email": email, "name": name})
    from auth import create_access_token
    from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES
    import json

    access_token = create_access_token(
        data={"sub": user.email, "tenant_id": tenant_id, "roles": roles},
        secret_key=JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
        expires_minutes=JWT_EXPIRE_MINUTES,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "email": user.email,
        "tenant_id": tenant_id,
        "roles": roles,
    }
</task_progress>
</write_to_file>