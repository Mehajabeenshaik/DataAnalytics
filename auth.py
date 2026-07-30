import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES, AUTH_DB_PATH


AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username    TEXT PRIMARY KEY,
    hashed_pw   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'viewer'
);
"""

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app = FastAPI(title="DataAnalytics Auth", version="1.0")


def _get_auth_db():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    conn = _get_auth_db()
    conn.executescript(AUTH_SCHEMA)
    existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing == 0:
        conn.execute(
            "INSERT INTO users (username, hashed_pw, role) VALUES (?, ?, ?)",
            ("admin", pwd_context.hash("admin123"), "admin"),
        )
        conn.execute(
            "INSERT INTO users (username, hashed_pw, role) VALUES (?, ?, ?)",
            ("viewer", pwd_context.hash("viewer123"), "viewer"),
        )
        conn.commit()
        print("Auth DB seeded: admin/admin123 (admin), viewer/viewer123 (viewer)")
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


@app.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
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


@app.get("/admin/reseed", dependencies=[Depends(require_admin)])
async def reseed_data():
    from data_layer import init_db
    init_db(force_reseed=True)
    return {"status": "success", "message": "Database reseeded"}


@app.get("/admin/pii-vault/{customer_id}", dependencies=[Depends(require_admin)])
async def get_pii_vault(customer_id: int):
    import sqlite3
    from config import PII_VAULT_PATH
    conn = sqlite3.connect(PII_VAULT_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM pii_vault WHERE customer_id = ?", (customer_id,)
    ).fetchall()
    conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail="Customer not found in PII vault")
    return {"customer_id": customer_id, "pii_records": [dict(r) for r in rows]}
