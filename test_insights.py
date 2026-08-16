"""Tests for Phase 9 — proactive insight generation.

Covers:
  - dataset with an obvious outlier -> outlier insight present
  - dataset with a column >5% null -> missingness insight present
  - dataset with no date column -> no trend insight (no crash)
  - insights list never exceeds 4 items
  - one failing check (tool raising) does not prevent other insights
"""

import pandas as pd

import stats_tools
from data_source import DataSource
from insights import generate_insights


class FakeCatalogService:
    def get_approved_metrics(self):
        return {}


def _ds(df: pd.DataFrame) -> DataSource:
    ds = DataSource()
    ds.load_dataframe(df)
    return ds


def test_outlier_insight_present():
    df = pd.DataFrame({
        "revenue": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 100.0],
        "region": ["N", "S", "N", "S", "N", "S", "N", "S", "N"],
    })
    insights = generate_insights(_ds(df), FakeCatalogService())
    assert any(i["type"] == "outlier" for i in insights)


def test_missingness_insight_present():
    df = pd.DataFrame({
        "status": ["a", "b", None, "c", "a", None, "b", "c"] * 2,
        "flag": [1, 2, 3, 4, 5, 6, 7, 8] * 2,
    })
    insights = generate_insights(_ds(df), FakeCatalogService())
    assert any(i["type"] == "missingness" for i in insights)


def test_no_date_column_no_crash_no_trend():
    df = pd.DataFrame({
        "revenue": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "score": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
    })
    insights = generate_insights(_ds(df), FakeCatalogService())
    assert isinstance(insights, list)  # did not raise
    assert all(i["type"] != "trend" for i in insights)


def test_capped_at_four():
    data = {}
    for i in range(10):
        data[f"col_{i}"] = ["x", None, "y", None] * 4  # 50% nulls each
    insights = generate_insights(_ds(pd.DataFrame(data)), FakeCatalogService())
    assert len(insights) <= 4


def test_one_failing_check_does_not_block_others(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("tool failed")

    monkeypatch.setattr(stats_tools, "run_stats_tool", boom)

    df = pd.DataFrame({
        "revenue": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "status": ["a", "b", None, "c", "a", "b", None, "c"],
    })
    insights = generate_insights(_ds(df), FakeCatalogService())
    assert any(i["type"] == "missingness" for i in insights)  # survives the RuntimeError