"""
File-based store for the enterprise identity layer.

Layout:
  data/tenants/
    orgs/<org_id>.yaml
    tenants/<tenant_id>.yaml
    users/<user_id>.yaml
    memberships/<id>.yaml

Local-first; documented migration path to Postgres later.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import Org, Tenant, User, Membership


class TenantStore:
    """Low-level persistence for orgs, tenants, users, memberships."""

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