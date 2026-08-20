"""Tests for Phase 3: per-tenant catalog scoping of propose/approve."""

import pytest

from catalog.models import MetricDefinition, MetricProposal
from catalog.service import CatalogService


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


@pytest.fixture
def tenant_catalogs(tmp_path):
    """Two CatalogService instances with isolated tenant roots."""
    svc_a = CatalogService(tenant_id="tenant_a")
    svc_a.store.root = tmp_path / "catalog" / "tenant_a"
    svc_a.store.current = svc_a.store.root / "current"
    svc_a.store.proposals_dir = svc_a.store.root / "proposals"
    svc_a.store.history = svc_a.store.root / "history"
    for d in (svc_a.store.current, svc_a.store.proposals_dir, svc_a.store.history):
        d.mkdir(parents=True, exist_ok=True)

    svc_b = CatalogService(tenant_id="tenant_b")
    svc_b.store.root = tmp_path / "catalog" / "tenant_b"
    svc_b.store.current = svc_b.store.root / "current"
    svc_b.store.proposals_dir = svc_b.store.root / "proposals"
    svc_b.store.history = svc_b.store.root / "history"
    for d in (svc_b.store.current, svc_b.store.proposals_dir, svc_b.store.history):
        d.mkdir(parents=True, exist_ok=True)

    return svc_a, svc_b


def test_propose_only_affects_correct_tenant(tenant_catalogs):
    svc_a, svc_b = tenant_catalogs

    pid = svc_a.propose(make_proposal("tenant_a_metric"))

    # Only tenant A has the pending proposal.
    assert len(svc_a.list_pending()) == 1
    assert len(svc_b.list_pending()) == 0

    # Tenant B's catalog has no trace of it.
    assert "tenant_a_metric" not in svc_b.get_approved_metrics()


def test_approve_only_affects_correct_tenant(tenant_catalogs):
    svc_a, svc_b = tenant_catalogs

    pid = svc_a.propose(make_proposal("tenant_a_metric"))
    svc_a.approve(pid, approved_by="admin_a")

    # Tenant A sees it approved.
    assert "tenant_a_metric" in svc_a.get_approved_metrics()

    # Tenant B does NOT see it.
    assert "tenant_a_metric" not in svc_b.get_approved_metrics()
    assert len(svc_b.list_pending()) == 0


def test_reject_only_affects_correct_tenant(tenant_catalogs):
    svc_a, svc_b = tenant_catalogs

    pid = svc_a.propose(make_proposal("tenant_a_metric"))
    svc_a.reject(pid, rejected_by="admin_a", reason="no")

    # Tenant A: rejected, not approved.
    assert "tenant_a_metric" not in svc_a.get_approved_metrics()
    assert len(svc_a.list_pending()) == 0

    # Tenant B: completely unaffected.
    assert "tenant_a_metric" not in svc_b.get_approved_metrics()
    assert len(svc_b.list_pending()) == 0