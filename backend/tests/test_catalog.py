"""Tests for the versioned metric catalog (catalog package).

Covers:
  - propose → pending
  - approve → appears in approved catalog + version bump
  - reject → does not appear
  - LLM catalog only contains approved metrics
  - auto metrics are seeded once (never overwritten)
  - backward-compatible get_approved_metrics() shape
"""

import pandas as pd
import pytest

from data_source import DataSource
from catalog.models import MetricDefinition, MetricProposal
from catalog.store import CatalogStore
from catalog.service import CatalogService


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5, 6],
            "customer_id": [10, 10, 20, 30, 30, 40],
            "revenue": [100.0, 200.0, 300.0, 150.0, 250.0, 400.0],
            "quantity": [1, 2, 3, 1, 2, 4],
            "region": ["North", "South", "North", "East", "West", "South"],
            "category": ["A", "B", "A", "C", "B", "A"],
            "order_date": pd.to_datetime(
                ["2024-01-15", "2024-02-20", "2024-03-10", "2024-04-05", "2024-05-12", "2024-06-18"]
            ),
        }
    )


@pytest.fixture
def ds(sample_df):
    ds = DataSource()
    ds.load_dataframe(sample_df)
    return ds


@pytest.fixture
def store(tmp_path):
    """Isolated catalog store per test — never touches the real data/catalog."""
    return CatalogStore(tmp_path / "catalog")


@pytest.fixture
def svc(store):
    return CatalogService(store)


def make_proposal(name: str = "median_revenue", column: str = "revenue") -> MetricProposal:
    return MetricProposal(
        metric=MetricDefinition(
            name=name,
            synonyms=[f"{name.replace('_', ' ')}"],
            description=f"Median of {column}.",
            column=column,
            agg="mean",
            groupby=None,
            base_filters={},
            status="pending",
            source="proposed",
            risk="low",
            created_by="agent",
        ),
        question="What is the median revenue?",
        reason="User asked for a median.",
        proposed_by="agent",
    )


# ── propose → pending ─────────────────────────────────────────────────────

def test_propose_creates_pending(svc):
    proposal = make_proposal()
    proposal_id = svc.propose(proposal)

    assert proposal_id == proposal.proposal_id
    pending = svc.list_pending()
    assert len(pending) == 1
    assert pending[0].proposal_id == proposal_id
    assert pending[0].status == "pending"

    # Not yet in the approved catalog.
    assert proposal.metric.name not in svc.get_approved_metrics()


# ── approve → appears in approved catalog + version bump ──────────────────

def test_approve_adds_to_catalog_and_bumps_version(svc):
    proposal = make_proposal()
    proposal_id = svc.propose(proposal)

    metric = svc.approve(proposal_id, approved_by="you")

    assert metric.status == "approved"
    assert metric.approved_by == "you"
    assert metric.approved_at is not None
    assert metric.proposal_id == proposal_id

    # Now visible in the approved catalog.
    approved = svc.get_approved_metrics()
    assert proposal.metric.name in approved
    assert approved[proposal.metric.name]["column"] == "revenue"

    # Version history was bumped.
    versions = svc.list_versions()
    assert len(versions) == 1
    assert versions[0]["version"] == "v001"
    assert versions[0]["count"] == 1

    # Proposal is no longer pending.
    assert len(svc.list_pending()) == 0


def test_approve_twice_raises(svc):
    proposal = make_proposal()
    proposal_id = svc.propose(proposal)
    svc.approve(proposal_id, approved_by="you")
    with pytest.raises(ValueError):
        svc.approve(proposal_id, approved_by="you")


# ── reject → does not appear ──────────────────────────────────────────────

def test_reject_never_enters_catalog(svc):
    proposal = make_proposal()
    proposal_id = svc.propose(proposal)

    svc.reject(proposal_id, rejected_by="you", reason="too broad")

    assert proposal.metric.name not in svc.get_approved_metrics()
    assert len(svc.list_pending()) == 0

    # Proposal is recorded as rejected with the review note.
    proposals = svc.list_proposals()
    assert len(proposals) == 1
    assert proposals[0].status == "rejected"
    assert proposals[0].review_note == "too broad"


def test_reject_twice_raises(svc):
    proposal = make_proposal()
    proposal_id = svc.propose(proposal)
    svc.reject(proposal_id, rejected_by="you", reason="no")
    with pytest.raises(ValueError):
        svc.reject(proposal_id, rejected_by="you", reason="no")


# ── LLM catalog only contains approved metrics ────────────────────────────

def test_llm_catalog_only_approved(svc):
    # Seed auto metrics (all approved).
    svc.seed_from_datasource(ds_factory())
    auto_count = len(svc.get_approved_metrics())
    assert auto_count > 0

    # Propose a new metric but don't approve it.
    proposal = make_proposal(name="pending_metric")
    svc.propose(proposal)

    # Reject another.
    rejected = make_proposal(name="rejected_metric")
    svc.propose(rejected)
    svc.reject(rejected.proposal_id, rejected_by="you", reason="no")

    llm_catalog = svc.get_catalog_for_llm()
    names = {m["name"] for m in llm_catalog}

    assert "pending_metric" not in names
    assert "rejected_metric" not in names
    # Every entry is name/synonyms/description only (no raw SQL/columns).
    for entry in llm_catalog:
        assert set(entry.keys()) == {"name", "synonyms", "description"}


def test_get_approved_metrics_legacy_shape(svc):
    svc.seed_from_datasource(ds_factory())
    approved = svc.get_approved_metrics()
    assert approved
    for name, m in approved.items():
        assert set(m.keys()) == {"synonyms", "description", "column", "agg", "groupby", "base_filters"}


# ── auto metrics are seeded once ──────────────────────────────────────────

def test_seed_once_only(svc, ds):
    first = svc.seed_from_datasource(ds)
    assert first > 0

    # Second seed is a no-op — never overwrites.
    second = svc.seed_from_datasource(ds)
    assert second == 0

    # Catalog still has exactly the first-seeded metrics.
    assert len(svc.get_approved_metrics()) == first


def test_seed_marks_auto_metrics_approved(svc, ds):
    svc.seed_from_datasource(ds)
    approved = svc.store.load_approved()
    assert approved
    for m in approved.values():
        assert m.status == "approved"
        assert m.source == "auto"


def test_seed_does_not_overwrite_human_approved(svc, ds):
    # Seed auto metrics first.
    svc.seed_from_datasource(ds)

    # Approve a new human-proposed metric.
    proposal = make_proposal(name="human_metric")
    proposal_id = svc.propose(proposal)
    svc.approve(proposal_id, approved_by="you")

    # Re-seeding must not wipe the human-approved metric.
    svc.seed_from_datasource(ds)
    approved = svc.get_approved_metrics()
    assert "human_metric" in approved


# ── helper ────────────────────────────────────────────────────────────────

def ds_factory():
    """Build a fresh DataSource for seeding tests that don't need the fixture."""
    df = pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "revenue": [100.0, 200.0, 300.0],
            "region": ["North", "South", "North"],
        }
    )
    d = DataSource()
    d.load_dataframe(df)
    return d