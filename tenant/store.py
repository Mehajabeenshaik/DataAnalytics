"""
tenant/store.py — store factory + file-based implementation.

The file-based TenantStore class is preserved verbatim for full backward
compatibility.  get_store() is the factory that selects between FileStore
and PostgresTenantStore based on config.TENANT_STORE.

    TENANT_STORE=file      → FileTenantStore  (default)
    TENANT_STORE=postgres  → PostgresTenantStore (requires psycopg2 + DATABASE_URL)
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import Org, Tenant, User, Membership


# ---------------------------------------------------------------------------
# File-based store (original implementation, unchanged)
# ---------------------------------------------------------------------------

class FileTenantStore:
    """Low-level file-based persistence for orgs, tenants, users, memberships.

    Layout::

        data/tenants/
            orgs/<org_id>.yaml
            tenants/<tenant_id>.yaml
            users/<user_id>.yaml
            memberships/<id>.yaml
    """

    def __init__(self, root: Path | str = Path("data/tenants")):
        self.root = Path(root)
        self.orgs_dir = self.root / "orgs"
        self.tenants_dir = self.root / "tenants"
        self.users_dir = self.root / "users"
        self.memberships_dir = self.root / "memberships"
        for d in (self.orgs_dir, self.tenants_dir, self.users_dir, self.memberships_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ── Orgs ──────────────────────────────────────────────────────────────

    def save_org(self, org: Org) -> None:
        (self.orgs_dir / f"{org.id}.yaml").write_text(
            yaml.dump(org.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
        )

    def load_org(self, org_id: str) -> Org | None:
        path = self.orgs_dir / f"{org_id}.yaml"
        if not path.exists():
            return None
        return Org(**yaml.safe_load(path.read_text()))

    def list_orgs(self) -> list[Org]:
        result = []
        for p in self.orgs_dir.glob("*.yaml"):
            try:
                result.append(Org(**yaml.safe_load(p.read_text())))
            except Exception:
                continue
        return result

    # ── Tenants ───────────────────────────────────────────────────────────

    def save_tenant(self, tenant: Tenant) -> None:
        (self.tenants_dir / f"{tenant.id}.yaml").write_text(
            yaml.dump(tenant.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
        )

    def load_tenant(self, tenant_id: str) -> Tenant | None:
        path = self.tenants_dir / f"{tenant_id}.yaml"
        if not path.exists():
            return None
        return Tenant(**yaml.safe_load(path.read_text()))

    def list_tenants(self, org_id: str | None = None) -> list[Tenant]:
        result = []
        for p in self.tenants_dir.glob("*.yaml"):
            try:
                t = Tenant(**yaml.safe_load(p.read_text()))
            except Exception:
                continue
            if org_id is None or t.org_id == org_id:
                result.append(t)
        return result

    # ── Users ─────────────────────────────────────────────────────────────

    def save_user(self, user: User) -> None:
        (self.users_dir / f"{user.id}.yaml").write_text(
            yaml.dump(user.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
        )

    def load_user(self, user_id: str) -> User | None:
        path = self.users_dir / f"{user_id}.yaml"
        if not path.exists():
            return None
        return User(**yaml.safe_load(path.read_text()))

    def find_user_by_email(self, email: str) -> User | None:
        for p in self.users_dir.glob("*.yaml"):
            try:
                u = User(**yaml.safe_load(p.read_text()))
            except Exception:
                continue
            if u.email.lower() == email.lower():
                return u
        return None

    # ── Memberships ───────────────────────────────────────────────────────

    def save_membership(self, membership: Membership) -> None:
        (self.memberships_dir / f"{membership.id}.yaml").write_text(
            yaml.dump(membership.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )

    def load_membership(self, membership_id: str) -> Membership | None:
        path = self.memberships_dir / f"{membership_id}.yaml"
        if not path.exists():
            return None
        return Membership(**yaml.safe_load(path.read_text()))

    def list_memberships(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        org_id: str | None = None,
    ) -> list[Membership]:
        result = []
        for p in self.memberships_dir.glob("*.yaml"):
            try:
                m = Membership(**yaml.safe_load(p.read_text()))
            except Exception:
                continue
            if user_id and m.user_id != user_id:
                continue
            if tenant_id and m.tenant_id != tenant_id:
                continue
            if org_id and m.org_id != org_id:
                continue
            result.append(m)
        return result


# ---------------------------------------------------------------------------
# Backward-compat alias
# TenantStore is the name used everywhere else in the codebase.  It now
# resolves to FileTenantStore so existing code needs zero changes.
# ---------------------------------------------------------------------------

TenantStore = FileTenantStore


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_store(
    store_type: str | None = None,
    *,
    file_root: Path | str | None = None,
    dsn: str | None = None,
) -> FileTenantStore:  # return type is the structural supertype (duck-typed)
    """Return the appropriate store based on config.TENANT_STORE.

    Args:
        store_type: Override for the store type (``"file"`` or ``"postgres"``).
                    When *None* the value from ``config.TENANT_STORE`` is used.
        file_root:  Override for the file store root directory.
        dsn:        Override for the Postgres DSN.  When *None* the value from
                    ``config.TENANT_DATABASE_URL`` is used.
    """
    if store_type is None:
        from config import TENANT_STORE as _cfg_store
        store_type = _cfg_store

    store_type = (store_type or "file").strip().lower()

    if store_type == "postgres":
        if dsn is None:
            from config import TENANT_DATABASE_URL as _cfg_dsn
            dsn = _cfg_dsn
        if not dsn:
            raise RuntimeError(
                "TENANT_STORE=postgres requires TENANT_DATABASE_URL to be set."
            )
        from .postgres_store import PostgresTenantStore
        return PostgresTenantStore(dsn)  # type: ignore[return-value]

    # Default: file
    root = Path(file_root) if file_root else Path("data/tenants")
    return FileTenantStore(root)