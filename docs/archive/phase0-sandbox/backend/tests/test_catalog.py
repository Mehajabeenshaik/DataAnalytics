import os
from pathlib import Path

import pytest

from backend.app.catalog.service import CatalogService
from backend.app.catalog.models import MetricProposal
from backend.app.metric_factory import seed_metrics
from backend.app.catalog.store import set as store_set

@pytest.fixture(scope="function")
def catalog_service():
    cs = CatalogService()
    # Ensure a clean store (clear the internal dict)
    from backend.app.catalog.store import _store
    _store.clear()
    # Seed approved metrics
    for metric in seed_metrics():
        store_set(metric)
    return cs

def test_list_approved_and_get(catalog_service):
    approved = catalog_service.list_approved()
    assert len(approved) >= 4
    names = {m.name for m in approved}
    assert "total_revenue" in names
    metric = catalog_service.get("total_revenue")
    assert metric is not None
    assert metric.description == "Total revenue across all rows."

def test_propose_approve_reject(catalog_service):
    proposal = MetricProposal(
        name="new_metric",
        description="A brand new metric for testing",
        synonyms=["nm"],
        sql_template="SELECT 1",
        allowed_filters=[],
        version=1,
    )
    catalog_service.propose(proposal)
    pending = catalog_service.get("new_metric")
    assert pending is not None
    assert pending.status == "proposed"
    # Approve
    catalog_service.approve("new_metric")
    approved = catalog_service.get("new_metric")
    assert approved.status == "approved"
    # Reject another metric
    catalog_service.reject("total_revenue")
    rejected = catalog_service.get("total_revenue")
    assert rejected.status == "rejected"
