"""
High-level API for the enterprise identity & isolation layer.

Provides org/tenant/user/membership management and RBAC helpers. All
operations are tenant-scoped by construction.
"""

from __future__ import annotations

from .models import Org, Tenant, User, Membership, AuthContext
from .store import TenantStore, get_store


class TenantService:
    """Facade over a TenantStore for identity + isolation operations.

    By default, the store backend is chosen from config via ``get_store()``.
    Pass an explicit ``store`` instance to override (e.g. in tests).
    """

    def __init__(self, store: TenantStore | None = None):
        self.store = store if store is not None else get_store()

    # ── Orgs ──────────────────────────────────────────────────────────────

    def create_org(self, name: str) -> Org:
        org = Org(name=name)
        self.store.save_org(org)
        return org

    def get_org(self, org_id: str) -> Org | None:
        return self.store.load_org(org_id)

    def list_orgs(self) -> list[Org]:
        return self.store.list_orgs()

    # ── Tenants ───────────────────────────────────────────────────────────

    def create_tenant(self, org_id: str, name: str) -> Tenant:
        tenant = Tenant(org_id=org_id, name=name)
        self.store.save_tenant(tenant)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self.store.load_tenant(tenant_id)

    def list_tenants_for_org(self, org_id: str) -> list[Tenant]:
        return self.store.list_tenants(org_id=org_id)

    # ── Users ─────────────────────────────────────────────────────────────

    def create_user(self, email: str, display_name: str = "") -> User:
        existing = self.store.find_user_by_email(email)
        if existing:
            return existing
        user = User(email=email, display_name=display_name)
        self.store.save_user(user)
        return user

    def get_user(self, user_id: str) -> User | None:
        return self.store.load_user(user_id)

    def find_user_by_email(self, email: str) -> User | None:
        return self.store.find_user_by_email(email)

    # ── Memberships ───────────────────────────────────────────────────────

    def add_user(
        self,
        user_id: str,
        role: str,
        tenant_id: str | None = None,
        org_id: str | None = None,
    ) -> Membership:
        membership = Membership(
            user_id=user_id,
            tenant_id=tenant_id,
            org_id=org_id,
            role=role,
        )
        self.store.save_membership(membership)
        return membership

    def get_memberships(
        self,
        user_id: str | None = None,
        tenant_id: str | None = None,
        org_id: str | None = None,
    ) -> list[Membership]:
        return self.store.list_memberships(
            user_id=user_id, tenant_id=tenant_id, org_id=org_id
        )

    def roles_for_user(self, user_id: str, tenant_id: str) -> list[str]:
        """Return the roles a user has within a tenant (or its org)."""
        roles = []
        for m in self.store.list_memberships(user_id=user_id):
            if m.tenant_id == tenant_id:
                roles.append(m.role)
            elif m.org_id:
                # Org-level membership grants roles across that org's tenants.
                tenant = self.store.load_tenant(tenant_id)
                if tenant and tenant.org_id == m.org_id:
                    roles.append(m.role)
        return roles

    # ── RBAC ──────────────────────────────────────────────────────────────

    def require_role(
        self,
        ctx: AuthContext,
        allowed_roles: list[str],
    ) -> None:
        """Raise PermissionError if the AuthContext lacks an allowed role."""
        if not any(r in ctx.roles for r in allowed_roles):
            raise PermissionError(
                f"Role(s) {allowed_roles} required; user has {ctx.roles}"
            )

    def build_auth_context(
        self,
        tenant_id: str,
        user_id: str | None = None,
        auth_method: str = "api_key",
    ) -> AuthContext:
        """Build an AuthContext for a tenant, resolving the user's roles."""
        roles = []
        org_id = None
        tenant = self.store.load_tenant(tenant_id)
        if tenant:
            org_id = tenant.org_id
        if user_id:
            roles = self.roles_for_user(user_id, tenant_id)
        return AuthContext(
            user_id=user_id,
            tenant_id=tenant_id,
            org_id=org_id,
            roles=roles,
            auth_method=auth_method,
        )