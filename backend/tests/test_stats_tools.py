"""Tests for Phase 2 statistical tools — stats_tools.py."""

import pandas as pd
import pytest

from data_source import DataSource
from stats_tools import (
    describe,
    value_counts,
    correlation,
    group_compare,
    missingness,
    trend,
    run_stats_tool,
    ALLOWED_STATS_TOOLS,
    VALID_TOOL_NAMES,
)


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


def test_describe_all_columns(ds):
    result = describe(ds)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 7
    assert "column" in result.columns
    assert "mean" in result.columns


def test_describe_numeric_column(ds):
    result = describe(ds, ["revenue"])
    assert len(result) == 1
    row = result.iloc[0]
    assert row["column"] == "revenue"
    assert row["dtype"] == "numeric"
    assert row["mean"] == pytest.approx(233.33, rel=1e-2)
    assert row["min"] == 100.0
    assert row["max"] == 400.0
    assert row["nulls"] == 0


def test_describe_categorical_column(ds):
    result = describe(ds, ["region"])
    assert len(result) == 1
    row = result.iloc[0]
    assert row["column"] == "region"
    assert row["dtype"] == "categorical"
    assert row["n_unique"] == 4


def test_describe_invalid_column(ds):
    with pytest.raises(ValueError, match="not found"):
        describe(ds, ["nonexistent_col"])


def test_value_counts(ds):
    result = value_counts(ds, "region")
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 4
    assert "value" in result.columns
    assert "count" in result.columns
    assert "pct" in result.columns
    south_row = result[result["value"] == "South"]
    assert south_row.iloc[0]["count"] == 2


def test_value_counts_top_n(ds):
    result = value_counts(ds, "region", top_n=2)
    assert len(result) == 2


def test_value_counts_invalid_column(ds):
    with pytest.raises(ValueError, match="not found"):
        value_counts(ds, "nonexistent_col")


def test_correlation_positive(ds):
    result = correlation(ds, "revenue", "quantity")
    assert isinstance(result, float)
    assert -1.0 <= result <= 1.0
    assert result > 0


def test_correlation_self(ds):
    result = correlation(ds, "revenue", "revenue")
    assert result == pytest.approx(1.0, abs=1e-6)


def test_correlation_non_numeric(ds):
    with pytest.raises(ValueError, match="not numeric"):
        correlation(ds, "region", "category")


def test_correlation_invalid_column(ds):
    with pytest.raises(ValueError, match="not found"):
        correlation(ds, "revenue", "nonexistent_col")


def test_group_compare_sum(ds):
    result = group_compare(ds, "revenue", "region", agg="sum")
    assert isinstance(result, pd.Series)
    assert len(result) == 4
    assert result["South"] == 600.0
    assert result["North"] == 400.0


def test_group_compare_mean(ds):
    result = group_compare(ds, "revenue", "region", agg="mean")
    assert isinstance(result, pd.Series)
    assert result["South"] == 300.0


def test_group_compare_invalid_agg(ds):
    with pytest.raises(ValueError, match="agg must be"):
        group_compare(ds, "revenue", "region", agg="median")


def test_group_compare_non_numeric_value(ds):
    with pytest.raises(ValueError, match="not numeric"):
        group_compare(ds, "region", "category")


def test_missingness_all_columns(ds):
    result = missingness(ds)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 7
    assert "column" in result.columns
    assert "null_pct" in result.columns
    assert (result["nulls"] == 0).all()


def test_missingness_specific_columns(ds):
    result = missingness(ds, ["revenue", "region"])
    assert len(result) == 2


def test_missingness_invalid_column(ds):
    with pytest.raises(ValueError, match="not found"):
        missingness(ds, ["nonexistent_col"])


def test_trend_monthly(ds):
    result = trend(ds, "order_date", "revenue", freq="M")
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 6
    assert "period" in result.columns
    assert "value" in result.columns
    assert "n" in result.columns


def test_trend_invalid_freq(ds):
    with pytest.raises(ValueError, match="freq must be"):
        trend(ds, "order_date", "revenue", freq="Y")


def test_trend_non_numeric_value(ds):
    with pytest.raises(ValueError, match="not numeric"):
        trend(ds, "order_date", "region")


def test_run_stats_tool_describe(ds):
    result = run_stats_tool(ds, "describe", {"columns": ["revenue"]})
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 1


def test_run_stats_tool_value_counts(ds):
    result = run_stats_tool(ds, "value_counts", {"column": "region", "top_n": 2})
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 2


def test_run_stats_tool_correlation(ds):
    result = run_stats_tool(ds, "correlation", {"col_a": "revenue", "col_b": "quantity"})
    assert isinstance(result, float)


def test_run_stats_tool_group_compare(ds):
    result = run_stats_tool(ds, "group_compare", {
        "value_col": "revenue", "group_col": "region", "agg": "sum"
    })
    assert isinstance(result, pd.Series)


def test_run_stats_tool_missingness(ds):
    result = run_stats_tool(ds, "missingness", {})
    assert isinstance(result, pd.DataFrame)


def test_run_stats_tool_trend(ds):
    result = run_stats_tool(ds, "trend", {
        "date_col": "order_date", "value_col": "revenue", "freq": "M"
    })
    assert isinstance(result, pd.DataFrame)


def test_run_stats_tool_unknown_tool(ds):
    with pytest.raises(ValueError, match="Unknown stats tool"):
        run_stats_tool(ds, "nonexistent_tool", {})


def test_allowed_stats_tools_catalog_size():
    assert len(ALLOWED_STATS_TOOLS) == 8


def test_valid_tool_names():
    expected = {
        "describe",
        "value_counts",
        "correlation",
        "group_compare",
        "missingness",
        "trend",
        "anomaly_detect",
        "filtered_agg",
    }
    assert VALID_TOOL_NAMES == expected


def test_each_tool_has_name_description_args():
    for tool in ALLOWED_STATS_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "args" in tool
        assert isinstance(tool["name"], str)
        assert isinstance(tool["description"], str)
        assert isinstance(tool["args"], dict)