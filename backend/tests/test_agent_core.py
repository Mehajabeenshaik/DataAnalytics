"""Tests for Phase 1 data-agnostic agent: data_source, metric_factory, agent_core."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_source import DataSource, ColumnProfile, TableProfile
from metric_factory import generate_metrics, get_metric_catalog_for_llm
from agent_core import select_metric, run_metric, explain, ask, MetricSelection


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_df():
    """A small, known DataFrame for deterministic testing."""
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
    """A DataSource loaded with sample_df."""
    ds = DataSource()
    ds.load_dataframe(sample_df)
    return ds


@pytest.fixture
def metrics(ds):
    """Auto-generated metrics from the sample DataSource."""
    return generate_metrics(ds)


def make_mock_provider(response_json: dict):
    provider = MagicMock()
    provider.generate.return_value = json.dumps(response_json)
    return provider


# ── DataSource tests ──────────────────────────────────────────────────────

def test_datasource_load_dataframe_creates_profile(ds):
    assert ds.profile is not None
    assert ds.profile.n_rows == 6
    assert ds.profile.n_cols == 7


def test_datasource_profile_column_types(ds):
    cols = {c.name: c for c in ds.profile.columns}
    assert cols["revenue"].is_numeric is True
    assert cols["quantity"].is_numeric is True
    assert cols["region"].is_categorical is True
    assert cols["category"].is_categorical is True
    assert cols["order_id"].is_numeric is True


def test_datasource_allowed_filter_columns(ds):
    """Categorical and temporal columns should be in the filter allowlist."""
    allowed = ds.allowed_filter_columns
    assert "region" in allowed
    assert "category" in allowed
    assert "order_date" in allowed
    # With only 6 rows, all columns have low cardinality (<=30),
    # so even numeric columns are included as potential filters.
    # The key safety property is that the LLM can only filter on
    # columns the DataSource explicitly allows -- it cannot inject
    # arbitrary column names.
    assert len(allowed) > 0


def test_datasource_query_returns_dataframe(ds):
    df = ds.query("SELECT * FROM data WHERE region = 'North'")
    assert len(df) == 2
    assert set(df["region"]) == {"North"}


def test_datasource_query_with_params(ds):
    df = ds.query("SELECT * FROM data WHERE region = ?", ["South"])
    assert len(df) == 2
    assert set(df["region"]) == {"South"}


def test_datasource_get_schema_card(ds):
    card = ds.get_schema_card()
    assert "Table: data" in card
    assert "Rows: 6" in card
    assert "revenue" in card
    assert "region" in card


def test_datasource_load_csv(sample_df):
    """Test loading from a CSV file."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        sample_df.to_csv(f.name, index=False)
        path = f.name

    try:
        ds = DataSource()
        ds.load_file(path)
        assert ds.profile.n_rows == 6
        assert ds.profile.n_cols == 7
    finally:
        Path(path).unlink()


def test_datasource_unsupported_file_type():
    ds = DataSource()
    with pytest.raises(ValueError, match="Unsupported file type"):
        ds.load_file("data.xlsx")


# ── metric_factory tests ──────────────────────────────────────────────────

def test_generate_metrics_creates_sum_metrics(metrics):
    assert "total_revenue" in metrics
    assert metrics["total_revenue"]["agg"] == "sum"
    assert metrics["total_revenue"]["column"] == "revenue"
    assert metrics["total_revenue"]["groupby"] is None


def test_generate_metrics_creates_avg_metrics(metrics):
    assert "avg_revenue" in metrics
    assert metrics["avg_revenue"]["agg"] == "mean"


def test_generate_metrics_creates_row_count(metrics):
    assert "row_count" in metrics
    assert metrics["row_count"]["agg"] == "count"
    assert metrics["row_count"]["column"] == "*"


def test_generate_metrics_creates_unique_metrics(metrics):
    assert "unique_order_id" in metrics
    assert metrics["unique_order_id"]["agg"] == "nunique"


def test_generate_metrics_creates_breakdown_metrics(metrics):
    """Numeric x categorical breakdowns should be generated."""
    assert "revenue_by_region" in metrics
    assert metrics["revenue_by_region"]["agg"] == "sum"
    assert metrics["revenue_by_region"]["groupby"] == "region"


def test_get_metric_catalog_excludes_sql_logic(metrics):
    """The LLM catalog must never expose column, agg, groupby, or base_filters."""
    catalog = get_metric_catalog_for_llm(metrics)
    for entry in catalog:
        assert "name" in entry
        assert "synonyms" in entry
        assert "description" in entry
        assert "column" not in entry
        assert "agg" not in entry
        assert "groupby" not in entry
        assert "base_filters" not in entry


def test_generate_metrics_raises_without_profile():
    ds = DataSource()
    with pytest.raises(RuntimeError, match="no profile"):
        generate_metrics(ds)


# ── agent_core: select_metric tests ───────────────────────────────────────

def test_select_metric_happy_path(ds, metrics):
    provider = make_mock_provider(
        {"metric_name": "total_revenue", "filters": {}, "no_match": False}
    )
    selection = select_metric("what is total revenue?", metrics, ds.allowed_filter_columns, provider)
    assert selection.metric_name == "total_revenue"
    assert selection.no_match is False


def test_select_metric_no_match(ds, metrics):
    provider = make_mock_provider({"no_match": True})
    selection = select_metric("what's the weather?", metrics, ds.allowed_filter_columns, provider)
    assert selection.no_match is True
    assert selection.metric_name is None


def test_select_metric_hallucinated_name_rejected(ds, metrics):
    """LLM invents a metric not in the catalog -- must be rejected."""
    provider = make_mock_provider(
        {"metric_name": "customer_lifetime_value", "filters": {}, "no_match": False}
    )
    selection = select_metric("what's CLV?", metrics, ds.allowed_filter_columns, provider)
    assert selection.metric_name is None
    assert selection.no_match is True


def test_select_metric_strips_non_allowlisted_filters(ds, metrics):
    """Filter keys outside the allowlist must be stripped."""
    provider = make_mock_provider(
        {
            "metric_name": "total_revenue",
            "filters": {"region": "North", "malicious_col": "drop table"},
            "no_match": False,
        }
    )
    selection = select_metric("revenue in North", metrics, ds.allowed_filter_columns, provider)
    assert "malicious_col" not in selection.filters
    assert "region" in selection.filters


def test_select_metric_malformed_json(ds, metrics):
    """Garbage JSON should degrade to no_match."""
    provider = MagicMock()
    provider.generate.return_value = "not valid json"
    selection = select_metric("revenue?", metrics, ds.allowed_filter_columns, provider)
    assert selection.no_match is True


# ── agent_core: run_metric tests ──────────────────────────────────────────

def test_run_metric_sum(ds, metrics):
    result = run_metric(ds, metrics["total_revenue"], {})
    assert isinstance(result, float)
    assert result == 1400.0  # 100+200+300+150+250+400


def test_run_metric_mean(ds, metrics):
    result = run_metric(ds, metrics["avg_revenue"], {})
    assert isinstance(result, float)
    assert result == pytest.approx(233.33, rel=1e-2)


def test_run_metric_count(ds, metrics):
    result = run_metric(ds, metrics["row_count"], {})
    assert isinstance(result, int)
    assert result == 6


def test_run_metric_nunique(ds, metrics):
    result = run_metric(ds, metrics["unique_order_id"], {})
    assert isinstance(result, int)
    assert result == 6


def test_run_metric_max(ds, metrics):
    """Regression: max_* metrics must execute (previously ValueError)."""
    assert "max_revenue" in metrics
    result = run_metric(ds, metrics["max_revenue"], {})
    assert result == 400.0


def test_run_metric_min(ds, metrics):
    """Regression: min_* metrics must execute (previously ValueError)."""
    assert "min_revenue" in metrics
    result = run_metric(ds, metrics["min_revenue"], {})
    assert result == 100.0


def test_run_metric_max_with_filter(ds, metrics):
    result = run_metric(ds, metrics["max_revenue"], {"region": "North"})
    assert result == 300.0  # North revenues: 100, 300


def test_run_metric_min_with_filter(ds, metrics):
    result = run_metric(ds, metrics["min_revenue"], {"region": "South"})
    assert result == 200.0  # South revenues: 200, 400


def test_run_metric_groupby_sum(ds, metrics):
    result = run_metric(ds, metrics["revenue_by_region"], {})
    assert isinstance(result, pd.Series)
    assert len(result) == 4  # North, South, East, West
    assert result.idxmax() == "South"  # 200+400=600


def test_run_metric_with_filter(ds, metrics):
    """Filters should restrict the result."""
    result_all = run_metric(ds, metrics["total_revenue"], {})
    result_north = run_metric(ds, metrics["total_revenue"], {"region": "North"})
    assert result_north < result_all
    assert result_north == 400.0  # 100+300


def test_run_metric_unknown_agg(ds):
    metric = {"column": "revenue", "agg": "median", "groupby": None, "base_filters": {}}
    with pytest.raises(ValueError, match="Unknown aggregation"):
        run_metric(ds, metric, {})


# ── agent_core: explain tests ─────────────────────────────────────────────

def test_explain_high_confidence():
    provider = make_mock_provider(
        {"answer": "Total revenue is 1400.", "confidence": "high", "caveat": None}
    )
    result = explain("what is revenue?", "total_revenue", 1400.0, provider)
    assert result["confidence"] == "high"
    assert "1400" in result["answer"]


def test_explain_downgrades_small_series():
    provider = make_mock_provider(
        {"answer": "Breakdown shown.", "confidence": "high", "caveat": None}
    )
    small_series = pd.Series([100, 200], index=["A", "B"])
    result = explain("breakdown", "revenue_by_region", small_series, provider)
    assert result["confidence"] == "low"
    assert "Small result set" in (result.get("caveat") or "")


def test_explain_malformed_response():
    provider = MagicMock()
    provider.generate.return_value = "garbage"
    result = explain("question", "metric", 42, provider)
    assert result["confidence"] == "low"
    assert result["caveat"] is not None


# ── agent_core: ask end-to-end tests ─────────────────────────────────────

def test_ask_happy_path(ds):
    """Full ask() flow: metric selected -> run_metric -> explain -> result dict."""
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({"metric_name": "total_revenue", "filters": {}, "no_match": False}),
        json.dumps({"answer": "Total revenue is 1400.", "confidence": "high", "caveat": None}),
    ]
    result = ask("what is total revenue?", ds, provider)
    assert result["metric_used"] == "total_revenue"
    assert result["confidence"] in ("high", "low")
    assert result["result"] == 1400.0
    assert result["filters_used"] == {}


def test_ask_no_match(ds):
    provider = make_mock_provider({"no_match": True})
    result = ask("what's the weather?", ds, provider)
    assert result["metric_used"] is None
    assert "don't have a reliable metric" in result["answer"]
    assert result["result"] is None


def test_ask_with_filter(ds):
    """ask() should pass filters through to run_metric."""
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps(
            {"metric_name": "total_revenue", "filters": {"region": "North"}, "no_match": False}
        ),
        json.dumps({"answer": "North revenue is 400.", "confidence": "high", "caveat": None}),
    ]
    result = ask("revenue in North region", ds, provider)
    assert result["metric_used"] == "total_revenue"
    assert result["result"] == 400.0
    assert result["filters_used"] == {"region": "North"}