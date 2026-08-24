"""
tenant/postgres_store.py — PostgreSQL-backed store for the enterprise identity layer.

Implements the exact same interface as the file-based TenantStore so it is a
drop-in replacement.  Uses psycopg2 directly (already a common transitive dep
through SQLAlchemy, but we don't require SQLAlchemy here — just psycopg2).

Schema is bootstrapped automatically on first connection via bootstrap_schema().
"""

from __future__ import annotations

from typing import Any

from .models import Org, Tenant, User, Membership

# ---------------------------------------------------------------------------
# SQL schema (idempotent — safe to run on every startup)
# ---------------------------------------------------------------------------

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS tenant_orgs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS tenant_tenants (
    id          TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL REFERENCES tenant_orgs(id),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS tenant_users (
    id           TEXT PRIMARY KEY,
    email        TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uidx_tenant_users_email
    ON tenant_users (lower(email));

CREATE TABLE IF NOT EXISTS tenant_memberships (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES tenant_users(id),
    tenant_id   TEXT REFERENCES tenant_tenants(id),
    org_id      TEXT REFERENCES tenant_orgs(id),
    role        TEXT NOT NULL DEFAULT 'analyst'
);

CREATE INDEX IF NOT EXISTS idx_memberships_user   ON tenant_memberships (user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_tenant ON tenant_memberships (tenant_id);
CREATE INDEX IF NOT EXISTS idx_memberships_org    ON tenant_memberships (org_id);
"""


def _row_to_dict(cursor, row) -> dict[str, Any]:
    """Convert a psycopg2 row tuple to a plain dict using cursor.description."""
    return {desc[0]: value for desc, value in zip(cursor.description, row)}


class PostgresTenantStore:
    """Postgres-backed persistence for orgs, tenants, users, memberships.

    Implements the same interface as the file-based TenantStore.
    Thread-safety: each public method opens and closes its own connection
    from the connection pool (or creates a new one if no pool is provided).
    """

    def __init__(self, dsn: str):
        """
        Args:
            dsn: A libpq connection string, e.g.
                 ``postgresql://user:pass@localhost:5432/tenantdb``
        """
        self._dsn = dsn
        self._ensure_psycopg2()
        self.bootstrap_schema()

    # ── Internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _ensure_psycopg2() -> None:
        # Availability probe: raise a friendly error instead of a raw
        # ImportError deep inside connect(). __import__ keeps pyflakes quiet
        # because the module is deliberately not bound for use here.
        try:
            __import__("psycopg2")
        except ImportError as exc:
            raise ImportError(
                "psycopg2 is required for TENANT_STORE=postgres. "
                "Install it with: pip install psycopg2-binary"
            ) from exc

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self._dsn)

    def _execute(
        self,
        sql: str,
        params: tuple = (),
        *,
        fetch: str = "none",   # "none" | "one" | "all"
    ):
        """Run a single statement inside its own autocommit-free transaction."""
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    if fetch == "one":
                        row = cur.fetchone()
                        desc = cur.description
                        return (_row_to_dict(cur, row) if row else None, desc)
                    if fetch == "all":
                        rows = cur.fetchall()
                        desc = cur.description
                        return ([_row_to_dict(cur, r) for r in rows], desc)
        finally:
            conn.close()

    def bootstrap_schema(self) -> None:
        """Create tables + indexes if they don't exist (idempotent)."""
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(BOOTSTRAP_SQL)
        finally:
            conn.close()

    # ── Orgs ──────────────────────────────────────────────────────────────

    def save_org(self, org: Org) -> None:
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tenant_orgs (id, name, created_at, status)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            name       = EXCLUDED.name,
                            status     = EXCLUDED.status
                        """,
                        (org.id, org.name, org.created_at, org.status),
                    )
        finally:
            conn.close()

    def load_org(self, org_id: str) -> Org | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, created_at, status FROM tenant_orgs WHERE id = %s",
                    (org_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                d = _row_to_dict(cur, row)
        finally:
            conn.close()
        return Org(**d)

    def list_orgs(self) -> list[Org]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, created_at, status FROM tenant_orgs ORDER BY created_at")
                rows = cur.fetchall()
                return [Org(**_row_to_dict(cur, r)) for r in rows]
        finally:
            conn.close()

    # ── Tenants ───────────────────────────────────────────────────────────

    def save_tenant(self, tenant: Tenant) -> None:
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tenant_tenants (id, org_id, name, created_at, status)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            org_id     = EXCLUDED.org_id,
                            name       = EXCLUDED.name,
                            status     = EXCLUDED.status
                        """,
                        (tenant.id, tenant.org_id, tenant.name, tenant.created_at, tenant.status),
                    )
        finally:
            conn.close()

    def load_tenant(self, tenant_id: str) -> Tenant | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, org_id, name, created_at, status FROM tenant_tenants WHERE id = %s",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                d = _row_to_dict(cur, row)
        finally:
            conn.close()
        return Tenant(**d)

    def list_tenants(self, org_id: str | None = None) -> list[Tenant]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if org_id is not None:
                    cur.execute(
                        "SELECT id, org_id, name, created_at, status FROM tenant_tenants WHERE org_id = %s ORDER BY created_at",
                        (org_id,),
                    )
                else:
                    cur.execute(
                        "SELECT id, org_id, name, created_at, status FROM tenant_tenants ORDER BY created_at"
                    )
                rows = cur.fetchall()
                return [Tenant(**_row_to_dict(cur, r)) for r in rows]
        finally:
            conn.close()

    # ── Users ─────────────────────────────────────────────────────────────

    def save_user(self, user: User) -> None:
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tenant_users (id, email, display_name, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            email        = EXCLUDED.email,
                            display_name = EXCLUDED.display_name
                        """,
                        (user.id, user.email, user.display_name, user.created_at),
                    )
        finally:
            conn.close()

    def load_user(self, user_id: str) -> User | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, display_name, created_at FROM tenant_users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                d = _row_to_dict(cur, row)
        finally:
            conn.close()
        return User(**d)

    def find_user_by_email(self, email: str) -> User | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, display_name, created_at FROM tenant_users WHERE lower(email) = lower(%s)",
                    (email,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                d = _row_to_dict(cur, row)
        finally:
            conn.close()
        return User(**d)

    # ── Memberships ───────────────────────────────────────────────────────

    def save_membership(self, membership: Membership) -> None:
        conn = self._connect()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tenant_memberships (id, user_id, tenant_id, org_id, role)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            user_id   = EXCLUDED.user_id,
                            tenant_id = EXCLUDED.tenant_id,
                            org_id    = EXCLUDED.org_id,
                            role      = EXCLUDED.role
                        """,
                        (
                            membership.id,
                            membership.user_id,
                            membership.tenant_id,
                            membership.org_id,
                            membership.role,
                        ),
                    )
        finally:
            conn.close()

    def load_membership(self, membership_id: str) -> Membership | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, user_id, tenant_id, org_id, role FROM tenant_memberships WHERE id = %s",
                    (membership_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                d = _row_to_dict(cur, row)
        finally:
            conn.close()
        return Membership(**d)

    def list_memberships(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        org_id: str | None = None,
    ) -> list[Membership]:
        clauses: list[str] = []
        params: list[str] = []

        if user_id is not None:
            clauses.append("user_id = %s")
            params.append(user_id)
        if tenant_id is not None:
            clauses.append("tenant_id = %s")
            params.append(tenant_id)
        if org_id is not None:
            clauses.append("org_id = %s")
            params.append(org_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT id, user_id, tenant_id, org_id, role FROM tenant_memberships {where} ORDER BY id"

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                return [Membership(**_row_to_dict(cur, r)) for r in rows]
        finally:
            conn.close()
