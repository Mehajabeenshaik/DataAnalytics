"""
Multi-tenant API key management for the embeddable widget.

Each embedding company gets a unique API key. The key is passed via
X-API-Key header from the widget. Tenant records live in auth.db
alongside the existing users table.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass, field

from config import AUTH_DB_PATH


TENANT_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    api_key         TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    settings        TEXT NOT NULL DEFAULT '{}',
    allowed_domains TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1
);
"""


@dataclass
class Tenant:
    api_key: str
    company_name: str
    settings: dict = field(default_factory=dict)
    allowed_domains: list[str] = field(default_factory=list)
    created_at: str = ""
    is_active: bool = True


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tenant_db() -> None:
    """Create the tenants table if it doesn't exist and guarantee default demo key exists."""
    from config import DEMO_API_KEY

    conn = _get_db()
    conn.executescript(TENANT_SCHEMA)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO tenants (api_key, company_name, settings, allowed_domains, created_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (DEMO_API_KEY, "Demo Company", json.dumps({"theme_color": "#7c5cfc"}), json.dumps(["localhost", "127.0.0.1"]), now),
    )
    conn.commit()
    conn.close()




def create_api_key(
    company_name: str,
    settings: dict | None = None,
    allowed_domains: list[str] | None = None,
) -> Tenant:
    """Generate a new API key for a company and store it.

    Args:
        company_name: Display name of the embedding company.
        settings: Per-tenant config (theme_color, logo_url, max_file_size_mb, etc).
        allowed_domains: List of domains allowed to use this key (not enforced yet).

    Returns:
        The created Tenant record.
    """
    api_key = f"ak_{secrets.token_hex(24)}"
    settings = settings or {}
    allowed_domains = allowed_domains or []
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_db()
    conn.execute(
        "INSERT INTO tenants (api_key, company_name, settings, allowed_domains, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (api_key, company_name, json.dumps(settings), json.dumps(allowed_domains), now),
    )
    conn.commit()
    conn.close()

    return Tenant(
        api_key=api_key,
        company_name=company_name,
        settings=settings,
        allowed_domains=allowed_domains,
        created_at=now,
    )


def validate_api_key(api_key: str) -> Tenant | None:
    """Look up an API key and return the Tenant if valid and active."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM tenants WHERE api_key = ? AND is_active = 1",
        (api_key,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return Tenant(
        api_key=row["api_key"],
        company_name=row["company_name"],
        settings=json.loads(row["settings"]),
        allowed_domains=json.loads(row["allowed_domains"]),
        created_at=row["created_at"],
        is_active=bool(row["is_active"]),
    )


def list_tenants() -> list[Tenant]:
    """List all active tenants."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM tenants WHERE is_active = 1").fetchall()
    conn.close()

    return [
        Tenant(
            api_key=row["api_key"],
            company_name=row["company_name"],
            settings=json.loads(row["settings"]),
            allowed_domains=json.loads(row["allowed_domains"]),
            created_at=row["created_at"],
            is_active=bool(row["is_active"]),
        )
        for row in rows
    ]


def revoke_api_key(api_key: str) -> bool:
    """Soft-delete a tenant by marking it inactive."""
    conn = _get_db()
    cursor = conn.execute(
        "UPDATE tenants SET is_active = 0 WHERE api_key = ?",
        (api_key,),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0
