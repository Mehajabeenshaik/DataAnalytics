"""Tests for Phase 3: RBAC (role-based access control)."""

import pytest

from tenant.service import TenantService
from tenant.models import AuthContext
from tenant.store import TenantStore


@pytest.fixture
def tenant_svc(tmp_path):
    return TenantService(TenantStore(tmp_path / "tenants"))


@pytest.fixture
def roles_env(tenant_svc):
    """Create an org, tenant, and users with different roles."""
    org = tenant_svc.create_org("Acme")
    tenant = tenant_svc.create_tenant(org.id, "Acme Analytics")

    admin = tenant_svc.create_user("admin@acme.com")
    analyst = tenant_svc.create_user("analyst@acme.com")
    viewer = tenant_svc.create_user("viewer@acme.com")

    tenant_svc.add_user(admin.id, role="admin", tenant_id=tenant.id)
    tenant_svc.add_user(analyst.id, role="analyst", tenant_id=tenant.id)
    tenant_svc.add_user(viewer.id, role="viewer", tenant_id=tenant.id)

    return {
        "tenant": tenant,
        "admin_ctx": tenant_svc.build_auth_context(tenant.id, admin.id),
        "analyst_ctx": tenant_svc.build_auth_context(tenant.id, analyst.id),
        "viewer_ctx": tenant_svc.build_auth_context(tenant.id, viewer.id),
    }


def test_admin_can_approve_metrics(roles_env):
    assert roles_env["admin_ctx"].is_admin()


def test_analyst_cannot_approve_metrics(roles_env):
    ctx = roles_env["analyst_ctx"]
    assert not ctx.is_admin()


def test_viewer_cannot_approve_metrics(roles_env):
    ctx = roles_env["viewer_ctx"]
    assert not ctx.is_admin()


def test_require_role_raises_for_analyst(roles_env):
    from tenant.service import TenantService as TS
    ts = TS()
    with pytest.raises(PermissionError):
        ts.require_role(roles_env["analyst_ctx"], ["admin", "owner"])


def test_require_role_passes_for_admin(roles_env):
    from tenant.service import TenantService as TS
    ts = TS()
    # Should not raise
    ts.require_role(roles_env["admin_ctx"], ["admin", "owner"])


def test_cross_org_no_access(tenant_svc):
    org1 = tenant_svc.create_org("Org1")
    tenant1 = tenant_svc.create_tenant(org1.id, "Tenant1")
    org2 = tenant_svc.create_org("Org2")
    tenant2 = tenant_svc.create_tenant(org2.id, "Tenant2")

    admin1 = tenant_svc.create_user("admin1@org1.com")
    tenant_svc.add_user(admin1.id, role="admin", tenant_id=tenant1.id)

    # Admin of tenant1 is an admin in tenant1...
    ctx1 = tenant_svc.build_auth_context(tenant1.id, admin1.id)
    assert ctx1.is_admin()

    # ...but has NO roles in tenant2 (different org → different tenant).
    ctx2 = tenant_svc.build_auth_context(tenant2.id, admin1.id)
    assert not ctx2.is_admin()

    # Accessing tenant2's catalog with admin1 must be denied.
    from tenant.service import TenantService as TS
    ts = TS()
    with pytest.raises(PermissionError):
        ts.require_role(ctx2, ["admin", "owner"])
