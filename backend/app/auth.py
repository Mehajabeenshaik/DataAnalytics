import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from config import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    AUTH_DB_PATH,
    LOG_LEVEL,
    CORS_ORIGINS,
    CORS_ALLOW_ALL,
    DEMO_API_KEY,
)


# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
_log = logging.getLogger("daana")


AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username    TEXT PRIMARY KEY,
    hashed_pw   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'viewer'
);
"""

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app = FastAPI(title="DataAnalytics", version="2.0")

# ── Rate limiting ─────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — allowlisted origins, config-driven (see PRODUCTION.md) ─────────
# A wildcard origin may NOT be combined with credentials (browser rule), so
# when CORS_ORIGINS=* we keep credentials off and rely on API keys for the
# widget. With an explicit allowlist we can still permit credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=not CORS_ALLOW_ALL,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security headers ──────────────────────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add basic hardening headers to every response.

    These are cheap, framework-level defenses that complement the safety
    invariants enforced elsewhere (approved metrics, PII masking, RBAC).
    Production TLS/proxy headers are configured at the reverse proxy.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Mount widget API router ───────────────────────────────────────────────
from .api_widget import widget_router  # noqa: E402
app.include_router(widget_router)


@app.get("/health")
async def health():
    """Liveness probe used by container orchestrators / docker healthcheck.

    Deliberately dependency-free: it must respond even if the LLM provider
    or auxiliary stores are temporarily unavailable, so orchestrators can
    restart only the dead container instead of the whole service.
    """
    return {"status": "ok", "service": "daana", "version": "2.0"}

# ── Mount SSO router ──────────────────────────────────────────────────────
from .auth_sso_routes import sso_router  # noqa: E402
app.include_router(sso_router)


def _get_auth_db():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    """Create the auth schema and seed a bootstrap admin only if the DB is empty.

    Production-safe behaviour:
    - Never hard-code a known password.
    - The bootstrap password comes from BOOTSTRAP_ADMIN_PASSWORD, or is
      randomly generated with secrets.token_urlsafe().
    - The plaintext is printed ONCE on first boot and never stored.
    - Subsequent starts do nothing (the DB already has users).
    """
    conn = _get_auth_db()
    conn.executescript(AUTH_SCHEMA)
    existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    if existing == 0:
        admin_user = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
        admin_pass = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")

        if not admin_pass:
            admin_pass = secrets.token_urlsafe(16)

        conn.execute(
            "INSERT INTO users (username, hashed_pw, role) VALUES (?, ?, ?)",
            (admin_user, pwd_context.hash(admin_pass), "admin"),
        )
        conn.commit()

        print("=" * 60)
        print("FIRST BOOT - BOOTSTRAP ADMIN CREATED")
        print(f"  Username : {admin_user}")
        print(f"  Password : {admin_pass}")
        print("  -> Change this password immediately after first login.")
        print("  -> Set BOOTSTRAP_ADMIN_PASSWORD in .env to control it on a fresh install.")
        print("=" * 60)

        _log.warning("Bootstrap admin '%s' created; change its password immediately.", admin_user)

    conn.close()


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str


class UserOut(BaseModel):
    username: str
    role: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"


def _authenticate(username: str, password: str) -> dict | None:
    conn = _get_auth_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row and pwd_context.verify(password, row["hashed_pw"]):
        return {"username": row["username"], "role": row["role"]}
    return None


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return UserOut(username=username, role=role)


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: UserOut = Depends(get_current_user)) -> UserOut:
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not permitted. Required: {self.allowed_roles}",
            )
        return user


require_admin = RoleChecker(["admin"])
require_any = RoleChecker(["admin", "viewer"])


@app.on_event("startup")
def startup():
    init_auth_db()
    from tenant import init_tenant_db
    init_tenant_db()

    # Pre-load local Ollama model in background thread to avoid cold-start delays
    import threading
    def _warmup_model():
        try:
            from llm_provider import get_provider
            provider = get_provider("ollama")
            provider.generate("hi", system_prompt="Respond in JSON: {\"status\": \"ok\"}")
            print("Ollama model pre-loaded into memory successfully!")
        except Exception as e:
            print(f"Ollama background warmup notice: {e}")

    threading.Thread(target=_warmup_model, daemon=True).start()


from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path


@app.get("/", response_class=HTMLResponse)
async def root():
    """API status page with the chat widget embedded right inline.

    Opening this URL shows the purple chat FAB (bottom-right) immediately —
    no need to hunt for frontend/app/index.html or widget-test.html.
    """
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DataAnalytics API</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                   background: #0e0e16; color: #eee; padding: 40px; max-width: 700px;
                   margin: auto; line-height: 1.6; }
            h1 { color: #7c5cfc; }
            pre { background: #1a1a24; padding: 16px; border-radius: 8px;
                  overflow-x: auto; color: #5ce1e6; font-size: 13px; }
            .badge { display: inline-block; padding: 4px 10px; background: #34d39922;
                     color: #34d399; border-radius: 4px; font-weight: 600; }
        </style>
    </head>
    <body>
        <h1>DataAnalytics API is live</h1>
        <p><span class="badge">OK</span> FastAPI backend running on port 8001</p>
        <p>The chat bot (purple FAB, bottom-right) is ready — no extra files needed.</p>

        <!-- Chat bot widget — loads immediately on this page -->
        <script
      src="/widget/widget.js"
      data-api-key="__DEMO_API_KEY__"
      data-api-url=""
      data-theme-color="#7c5cfc"></script>
    </body>
    </html>
    """.replace("__DEMO_API_KEY__", DEMO_API_KEY)


@app.get("/app", response_class=HTMLResponse)
async def spa():
    """Serve the full upload + ask UI (frontend/app/index.html)."""
    app_path = Path(__file__).resolve().parents[2] / "frontend" / "app" / "index.html"
    if not app_path.exists():
        return HTMLResponse("<h1>App not built</h1>", status_code=404)
    return FileResponse(str(app_path))


@app.get("/admin", response_class=HTMLResponse)
async def admin_ui():
    """Serve the metric-approval admin console (frontend/app/admin.html).

    The page itself talks to the admin API below (requires an admin JWT, so
    the HTML is public but every data call is role-gated).
    """
    app_path = Path(__file__).resolve().parents[2] / "frontend" / "app" / "admin.html"
    if not app_path.exists():
        return HTMLResponse("<h1>Admin UI not built</h1>", status_code=404)
    return FileResponse(str(app_path))



@app.post("/auth/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Login with per-IP rate limiting (10 attempts/minute) to slow brute force."""
    user = _authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return Token(
        access_token=token,
        token_type="bearer",
        role=user["role"],
        username=user["username"],
    )


@app.get("/auth/me", response_model=UserOut)
async def get_me(user: UserOut = Depends(get_current_user)):
    return user


# ── SSO / OIDC path (SSO-ready stub) ───────────────────────────────────────
# Integration points for WorkOS / Auth0 / Descope / Keycloak style OIDC.
# When OIDC_ENABLED=true, these endpoints become live:
#   1. GET /auth/login → redirect to the IdP authorization URL
#   2. GET /auth/callback → exchange the IdP code, look up / create the user,
#      and issue our own short-lived JWT carrying tenant_id + roles.
#   3. POST /auth/token → exchange an IdP-issued token for our JWT.
#
# The actual IdP flow lives in auth_oidc.py (authlib-based). Only the
# enabled flag is needed here for the disabled-mode 501 responses.
from config import OIDC_ENABLED


@app.get("/auth/login/sso")
async def sso_login():
    """Start the OIDC authorization-code flow.

    Redirects to the IdP authorize endpoint with a signed `state` (also set as
    an HttpOnly cookie) so the callback can reject forged returns.
    """
    if not OIDC_ENABLED:
        raise HTTPException(
            status_code=501,
            detail="OIDC is disabled. Set OIDC_ENABLED=true and configure OIDC_ISSUER/CLIENT_ID to enable SSO.",
        )

    from fastapi.responses import RedirectResponse

    from .auth_oidc import (
        OIDCClient,
        STATE_COOKIE,
        STATE_MAX_AGE_SECONDS,
        make_state,
        new_nonce,
    )

    client = OIDCClient()
    nonce = new_nonce()
    state = make_state(nonce)
    url = client.build_authorize_url(state=state, nonce=nonce)
    resp = RedirectResponse(url, status_code=307)
    resp.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return resp


@app.get("/auth/callback")
async def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Finish the OIDC flow: exchange the code, validate the ID token against
    the IdP's published JWKS, map roles, and issue our own short-lived JWT.
    """
    if not OIDC_ENABLED:
        raise HTTPException(status_code=501, detail="OIDC is disabled.")

    from fastapi.responses import JSONResponse

    from .auth_oidc import (
        OIDCClient,
        OIDCError,
        STATE_COOKIE,
        map_role,
        read_state,
    )

    if error:
        raise HTTPException(status_code=401, detail=f"IdP returned an error: {error}")

    # State must be present, signed by us, unexpired, and match the cookie.
    cookie_state = request.cookies.get(STATE_COOKIE)
    if not state or not cookie_state or state != cookie_state:
        raise HTTPException(status_code=401, detail="OIDC state mismatch")
    try:
        state_claims = read_state(state)
    except OIDCError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    nonce = state_claims.get("nonce")

    client = OIDCClient()
    try:
        tokens = client.exchange_code(code) if code else {}
        claims = client.validate_id_token(tokens.get("id_token", ""), nonce=nonce)
    except OIDCError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    email = claims["email"]
    role = map_role(claims)

    # Best-effort link to the tenant identity layer (optional dependency).
    tenant_id: str | None = None
    roles: list[str] = [role]
    try:
        from tenant.service import TenantService

        svc = TenantService()
        user = svc.ensure_user(email=email, name=claims.get("name", "")) if hasattr(svc, "ensure_user") else None
        if user is not None and hasattr(svc, "list_memberships_for_user"):
            memberships = svc.list_memberships_for_user(user.id)
            if len(memberships) == 1:
                tenant_id = memberships[0].tenant_id
                if memberships[0].role:
                    roles = [memberships[0].role]
    except Exception:
        pass  # tenant layer optional in minimal installs

    token = create_access_token(
        {
            "sub": email,
            "email": email,
            "role": role,
            "tenant_id": tenant_id,
            "roles": roles,
        }
    )
    resp = JSONResponse(
        {
            "access_token": token,
            "token_type": "bearer",
            "username": email,
            "role": role,
            "email": email,
            "tenant_id": tenant_id,
            "roles": roles,
        }
    )
    resp.delete_cookie(STATE_COOKIE)
    _log.info("OIDC login succeeded for '%s' (role=%s)", email, role)
    return resp


@app.post("/auth/token")
async def sso_token_exchange(payload: dict):
    """Exchange an IdP-issued token for our short-lived JWT.

    Integration point: validate the IdP token via the discovery document /
    JWKS, map the subject to a User + Membership, resolve tenant_id + roles,
    then return our own create_access_token() payload.
    """
    if not OIDC_ENABLED:
        raise HTTPException(status_code=501, detail="OIDC is disabled.")
    raise HTTPException(
        status_code=501,
        detail="OIDC integration point: validate the IdP token, resolve tenant_id + roles, and issue our JWT.",
    )


@app.post("/auth/register", response_model=UserOut, dependencies=[Depends(require_admin)])
async def register(user_data: UserCreate, admin: UserOut = Depends(require_admin)):
    conn = _get_auth_db()
    existing = conn.execute("SELECT 1 FROM users WHERE username = ?", (user_data.username,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")
    conn.execute(
        "INSERT INTO users (username, hashed_pw, role) VALUES (?, ?, ?)",
        (user_data.username, pwd_context.hash(user_data.password), user_data.role),
    )
    conn.commit()
    conn.close()
    return UserOut(username=user_data.username, role=user_data.role)


@app.post("/auth/users", response_model=UserOut, dependencies=[Depends(require_admin)])
async def create_user(body: UserCreate, admin: UserOut = Depends(require_admin)):
    """Create a new user (admin only). Alias of /auth/register for the admin console."""
    conn = _get_auth_db()
    try:
        conn.execute(
            "INSERT INTO users (username, hashed_pw, role) VALUES (?, ?, ?)",
            (body.username, pwd_context.hash(body.password), body.role),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")
    finally:
        conn.close()
    return UserOut(username=body.username, role=body.role)


MIN_PASSWORD_LENGTH = 10


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/auth/change-password")
async def change_password(
    body: PasswordChange,
    user: UserOut = Depends(get_current_user),
):
    """Change the logged-in user's own password.

    - 200 on success (old sessions' tokens remain valid until expiry).
    - 400 if the new password is below MIN_PASSWORD_LENGTH.
    - 401 if the current password is wrong or the token is invalid.
    """
    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters",
        )

    conn = _get_auth_db()
    try:
        row = conn.execute(
            "SELECT hashed_pw FROM users WHERE username = ?", (user.username,)
        ).fetchone()
        if not row or not pwd_context.verify(body.current_password, row["hashed_pw"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        conn.execute(
            "UPDATE users SET hashed_pw = ? WHERE username = ?",
            (pwd_context.hash(body.new_password), user.username),
        )
        conn.commit()
    finally:
        conn.close()

    _log.info("Password changed for user '%s'", user.username)
    return {"status": "password_changed", "username": user.username}


@app.get("/admin/reseed", dependencies=[Depends(require_admin)])
async def reseed_data():
    """Rebuild ecommerce.db (+ encrypted twin) with deterministic sample data."""
    import asyncio
    from data_layer import init_db

    loop = asyncio.get_running_loop()
    summary = await loop.run_in_executor(None, init_db)
    return {"status": "reseeded", **summary}


@app.get("/admin/pii-vault/{customer_id}", dependencies=[Depends(require_admin)])
async def get_pii_vault(customer_id: int):
    import sqlite3
    from config import PII_VAULT_ENCRYPTED_PATH
    from encryption import EncryptedDB

    # pii_masker.py ONLY ever writes to the Fernet-encrypted vault at
    # PII_VAULT_ENCRYPTED_PATH (pii_vault.db.enc) via EncryptedDB. The
    # previous version of this endpoint read the plaintext PII_VAULT_PATH
    # (pii_vault.db) directly — a file that is never created — so it always
    # 404'd, and even if it had existed, bypassing EncryptedDB would defeat
    # the encryption model entirely.
    with EncryptedDB(encrypted_path=PII_VAULT_ENCRYPTED_PATH) as tmp_db:
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM pii_vault WHERE customer_id = ?", (customer_id,)
        ).fetchall()
        conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="Customer not found in PII vault")
    return {"customer_id": customer_id, "pii_records": [dict(r) for r in rows]}


# ── Late import avoids circular import: admin_api imports get_current_user from auth ──
from .admin_api import admin_router  # noqa: E402
app.include_router(admin_router)
