"""Tests for Phase 3: cross-tenant isolation."""

import pandas as pd
import pytest

from catalog.models import MetricDefinition, MetricProposal
from catalog.service import CatalogService
from tenant.service import TenantService
from tenant.models import AuthContext
from tenant.isolation import require_tenant_context
from tenant_quotas import TenantQuota, set_quota
from audit_logger import log_action, export_audit
from cache import _make_cache_key


@pytest.fixture
def tenant_svc(tmp_path):
    from tenant.store import TenantStore
    return TenantService(TenantStore(tmp_path / "tenants"))


@pytest.fixture
def two_tenants(tmp_path):
    """Create two isolated catalog services for two tenants."""
    svc_a = CatalogService(tenant_id="tenant_a")
    svc_a.store.root = tmp_path / "catalog" / "tenant_a"
    svc_a.store.current = svc_a.store.root / "current"
    svc_a.store.proposals_dir = svc_a.store.root / "proposals"
    svc_a.store.history = svc_a.store.root / "history"

    svc_b = CatalogService(tenant_id="tenant_b")
    svc_b.store.root = tmp_path / "catalog" / "tenant_b"
    svc_b.store.current = svc_b.store.root / "current"
    svc_b.store.proposals_dir = svc_b.store.root / "proposals"
    svc_b.store.history = svc_b.store.root / "history"

    for svc in (svc_a, svc_b):
        svc.store.current.mkdir(parents=True, exist_ok=True)
        svc.store.proposals_dir.mkdir(parents=True, exist_ok=True)
        svc.store.history.mkdir(parents=True, exist_ok=True)
    return svc_a, svc_b


def make_proposal(name: str) -> MetricProposal:
    return MetricProposal(
        metric=MetricDefinition(
            name=name,
            synonyms=[name.replace("_", " ")],
            description=f"Metric {name}.",
            column="revenue",
            agg="sum",
            groupby=None,
            base_filters={},
            status="pending",
            source="proposed",
            risk="low",
            created_by="agent",
        ),
        question=f"Question for {name}",
        reason="Test",
        proposed_by="agent",
    )


# ── Tenant A cannot see Tenant B's catalog metrics ────────────────────────

def test_tenant_a_cannot_see_tenant_b_catalog(two_tenants):
    svc_a, svc_b = two_tenants

    # Tenant A has a metric
    proposal_a = make_proposal("metric_a_only")
    pid_a = svc_a.propose(proposal_a)
    svc_a.approve(pid_a, approved_by="admin_a")

    # Tenant B has a different metric
    proposal_b = make_proposal("metric_b_only")
    pid_b = svc_b.propose(proposal_b)
    svc_b.approve(pid_b, approved_by="admin_b")

    approved_a = svc_a.get_approved_metrics()
    approved_b = svc_b.get_approved_metrics()

    assert "metric_a_only" in approved_a
    assert "metric_a_only" not in approved_b
    assert "metric_b_only" in approved_b
    assert "metric_b_only" not in approved_a


def test_proposals_are_tenant_scoped(two_tenants):
    svc_a, svc_b = two_tenants
    svc_a.propose(make_proposal("pending_a"))
    svc_b.propose(make_proposal("pending_b"))

    pending_a = svc_a.list_pending()
    pending_b = svc_b.list_pending()

    assert len(pending_a) == 1
    assert len(pending_b) == 1
    assert pending_a[0].metric.name == "pending_a"
    assert pending_b[0].metric.name == "pending_b"


# ── Tenant A cannot read Tenant B's audit export ──────────────────────────

def test_audit_export_is_tenant_scoped(tmp_path):
    # Log two records for different tenants
    log_action("alice", "analyst", "QUERY", details={"q": "a"}, tenant_id="tenant_a")
    log_action("bob", "analyst", "QUERY", details={"q": "b"}, tenant_id="tenant_b")

    export_a = export_audit("tenant_a")
    export_b = export_audit("tenant_b")

    assert all(r["tenant_id"] == "tenant_a" for r in export_a)
    assert all(r["tenant_id"] == "tenant_b" for r in export_b)
    assert len(export_a) >= 1
    assert len(export_b) >= 1


# ── Cache key collision does not leak answers across tenants ──────────────

def test_cache_keys_are_tenant_scoped():
    key_a = _make_cache_key("What is revenue?", None, dataset_id="ds1", tenant_id="tenant_a")
    key_b = _make_cache_key("What is revenue?", None, dataset_id="ds1", tenant_id="tenant_b")
    assert key_a != key_b


# ── Missing tenant context → hard fail ────────────────────────────────────

def test_missing_tenant_context_fails():
    with pytest.raises(PermissionError):
        require_tenant_context(None)

    with pytest.raises(PermissionError):
        require_tenant_context("")


def test_valid_tenant_context_passes():
    assert require_tenant_context("tenant_a") == "tenant_a"


# ── Org/tenant model ──────────────────────────────────────────────────────

def test_create_org_tenant_user_membership(tenant_svc):
    org = tenant_svc.create_org("Acme")
    tenant = tenant_svc.create_tenant(org.id, "Acme Analytics")
    user = tenant_svc.create_user("alice@acme.com", "Alice")

    assert tenant_svc.get_tenant(tenant.id).org_id == org.id
    assert tenant_svc.find_user_by_email("alice@acme.com").id == user.id

    tenant_svc.add_user(user.id, role="admin", tenant_id=tenant.id)
    roles = tenant_svc.roles_for_user(user.id, tenant.id)
    assert "admin" in roles


def test_build_auth_context(tenant_svc):
    org = tenant_svc.create_org("Beta")
    tenant = tenant_svc.create_tenant(org.id, "Beta Tenant")
    user = tenant_svc.create_user("bob@beta.com")
    tenant_svc.add_user(user.id, role="analyst", tenant_id=tenant.id)

    ctx = tenant_svc.build_auth_context(tenant.id, user.id)
    assert ctx.tenant_id == tenant.id
    assert ctx.org_id == org.id
    assert "analyst" in ctx.roles
    assert not ctx.is_admin()