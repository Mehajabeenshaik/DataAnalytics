import pytest
from pathlib import Path

from backend.app.data_source import DataSource
from backend.app.stats_tools import (
    describe,
    trend,
    correlation,
    value_counts,
    missing_stats,
)

@pytest.fixture(scope="module")
def data_source():
    ds = DataSource()
    csv_path = Path(__file__).parent / "fixtures" / "sample.csv"
    ds.load_csv(csv_path)
    return ds

def test_describe(data_source):
    result = describe(data_source, "revenue")
    assert result["column"] == "revenue"
    assert "mean" in result["description"]

def test_trend(data_source):
    result = trend(data_source, "revenue", "date")
    assert isinstance(result, list)
    assert len(result) > 0
    # Each record should have the time column and the value column
    first = result[0]
    assert "date" in first and "revenue" in first

def test_correlation(data_source):
    result = correlation(data_source, "revenue", "orders")
    assert "pearson" in result
    # Correlation should be a float
    assert isinstance(result["pearson"], float)

def test_value_counts(data_source):
    result = value_counts(data_source, "region", top_n=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    assert "value" in result[0] and "count" in result[0]

def test_missing_stats(data_source):
    result = missing_stats(data_source)
    assert "total_rows" in result
    assert "missing_counts" in result
    assert "missing_percent" in result
    # All counts should be integers and percentages floats
    for cnt in result["missing_counts"].values():
        assert isinstance(cnt, int)
    for pct in result["missing_percent"].values():
        assert isinstance(pct, float)
