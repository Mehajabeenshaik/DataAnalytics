"""
Regression tests: max/min aggregation must work in BOTH execution paths.

There are two ways metrics reach run_metric():
  1. Legacy path: DataSource.get_metrics() -> metric_factory.generate_metrics()
  2. CatalogService path: CatalogService.seed_from_datasource() -> get_approved_metrics()

Both paths must produce metrics whose "agg" field ("max"/"min") is accepted
by the dispatch table in agent_core.run_metric(). If a fix only lands in one
path, one of these tests will fail.
"""

import pandas as pd
import pytest

from data_source import DataSource
from metric_factory import generate_metrics
from agent_core import run_metric
from catalog.service import CatalogService
from catalog.store import CatalogStore


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_df():
    """A small, known DataFrame for deterministic testing."""
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5, 6],
            "revenue": [100.0, 200.0, 300.0, 150.0, 250.0, 400.0],
            "quantity": [1, 2, 3, 1, 2, 4],
            "region": ["North", "South", "North", "East", "West", "South"],
        }
    )


@pytest.fixture
def ds(sample_df):
    """A DataSource loaded with sample_df."""
    ds = DataSource()
    ds.load_dataframe(sample_df)
    return ds


# ── Path 1: Legacy generate_metrics() ─────────────────────────────────────

def test_legacy_generate_metrics_emits_max_min(ds):
    """generate_metrics() must create max_<col>/min_<col> entries."""
    metrics = generate_metrics(ds)
    assert "max_revenue" in metrics
    assert metrics["max_revenue"]["agg"] == "max"
    assert metrics["max_revenue"]["column"] == "revenue"
    assert "min_revenue" in metrics
    assert metrics["min_revenue"]["agg"] == "min"
    assert metrics["min_revenue"]["column"] == "revenue"


def test_legacy_run_metric_max(ds):
    """run_metric with agg='max' returns the correct max value."""
    metrics = generate_metrics(ds)
    result = run_metric(ds, metrics["max_revenue"], {})
    assert result == 400.0  # max of [100, 200, 300, 150, 250, 400]


def test_legacy_run_metric_min(ds):
    """run_metric with agg='min' returns the correct min value."""
    metrics = generate_metrics(ds)
    result = run_metric(ds, metrics["min_revenue"], {})
    assert result == 100.0  # min of [100, 200, 300, 150, 250, 400]


def test_legacy_run_metric_max_with_filter(ds):
    """max with a filter must respect the filter."""
    metrics = generate_metrics(ds)
    result = run_metric(ds, metrics["max_revenue"], {"region": "North"})
    assert result == 300.0  # North revenues: 100, 300


def test_legacy_run_metric_min_with_filter(ds):
    """min with a filter must respect the filter."""
    metrics = generate_metrics(ds)
    result = run_metric(ds, metrics["min_revenue"], {"region": "South"})
    assert result == 200.0  # South revenues: 200, 400


# ── Path 2: CatalogService / durable catalog ──────────────────────────────

@pytest.fixture
def catalog_service(ds, tmp_path):
    """A CatalogService seeded from the DataSource, scoped to a temp dir."""
    service = CatalogService(store=CatalogStore(root=tmp_path / "catalog"))
    service.seed_from_datasource(ds, created_by="test")
    return service


def test_catalog_service_emits_max_min(catalog_service):
    """CatalogService.get_approved_metrics() must include max/min metrics."""
    approved = catalog_service.get_approved_metrics()
    assert "max_revenue" in approved
    assert approved["max_revenue"]["agg"] == "max"
    assert "min_revenue" in approved
    assert approved["min_revenue"]["agg"] == "min"


def test_catalog_service_run_metric_max(ds, catalog_service):
    """run_metric with a CatalogService-sourced max metric returns correct value."""
    approved = catalog_service.get_approved_metrics()
    result = run_metric(ds, approved["max_revenue"], {})
    assert result == 400.0


def test_catalog_service_run_metric_min(ds, catalog_service):
    """run_metric with a CatalogService-sourced min metric returns correct value."""
    approved = catalog_service.get_approved_metrics()
    result = run_metric(ds, approved["min_revenue"], {})
    assert result == 100.0


def test_catalog_service_run_metric_max_with_filter(ds, catalog_service):
    """max via CatalogService path with a filter must respect the filter."""
    approved = catalog_service.get_approved_metrics()
    result = run_metric(ds, approved["max_revenue"], {"region": "North"})
    assert result == 300.0


def test_catalog_service_run_metric_min_with_filter(ds, catalog_service):
    """min via CatalogService path with a filter must respect the filter."""
    approved = catalog_service.get_approved_metrics()
    result = run_metric(ds, approved["min_revenue"], {"region": "South"})
    assert result == 200.0


# ── Cross-path consistency ────────────────────────────────────────────────

def test_both_paths_produce_identical_agg_strings(ds, catalog_service):
    """The 'agg' field must be the exact same string in both paths."""
    legacy = generate_metrics(ds)
    approved = catalog_service.get_approved_metrics()

    assert legacy["max_revenue"]["agg"] == approved["max_revenue"]["agg"] == "max"
    assert legacy["min_revenue"]["agg"] == approved["min_revenue"]["agg"] == "min"