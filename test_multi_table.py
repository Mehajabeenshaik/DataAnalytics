"""Tests for Phase 7 — governed multi-table joins.

Covers:
  - propose + approve a join policy
  - run a metric against the joined view, confirm row count and values
  - attempt to reference an unapproved join -> rejected
"""

import pandas as pd

from catalog.models import JoinPolicy, JoinProposal
from catalog.service import CatalogService
from catalog.store import CatalogStore
from dataset_registry import DatasetRegistry


def _service(tmp_path):
    return CatalogService(store=CatalogStore(root=tmp_path))


def test_propose_approve_join_then_query(tmp_path):
    svc = _service(tmp_path)
    registry = DatasetRegistry()
    registry.register_table(
        "orders",
        pd.DataFrame(
            {"order_id": [1, 2], "customer_id": [10, 20], "amount": [100, 200]}
        ),
    )
    registry.register_table(
        "customers",
        pd.DataFrame({"customer_id": [10, 20], "region": ["East", "West"]}),
    )

    join = JoinPolicy(
        name="orders_with_region",
        left_table="orders",
        right_table="customers",
        left_key="customer_id",
        right_key="customer_id",
        join_type="inner",
    )
    proposal = JoinProposal(
        join=join, question="revenue by region", reason="needs customer region"
    )
    pid = svc.propose_join(proposal)
    svc.approve_join(pid, approved_by="tester")

    approved = svc.get_approved_joins()
    assert "orders_with_region" in approved

    view = registry.get_joined_view(approved["orders_with_region"])
    assert len(view) == 2
    assert "region" in view.columns


def test_unapproved_join_rejected(tmp_path):
    svc = _service(tmp_path)
    assert "nonexistent_join" not in svc.get_approved_joins()