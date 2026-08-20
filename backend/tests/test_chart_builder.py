"""Tests for Phase 8 — chart/visualization output from verified results."""

from chart_builder import build_chart_spec


def test_breakdown_produces_bar_chart():
    step = {"action": "run_metric", "target": "revenue_by_region",
            "result": {"East": 100, "West": 200, "North": 50}}
    spec = build_chart_spec(step)
    assert spec["mark"] == "bar"
    assert len(spec["data"]["values"]) == 3


def test_scalar_produces_no_chart():
    step = {"action": "run_metric", "target": "total_revenue", "result": 1400.0}
    assert build_chart_spec(step) is None


def test_time_series_produces_line_chart():
    step = {"action": "run_stats", "target": "trend",
            "result": {"2024-01-01": 100, "2024-01-02": 150}}
    spec = build_chart_spec(step)
    assert spec["mark"] == "line"


def test_large_breakdown_truncated():
    result = {f"cat_{i}": i for i in range(60)}
    step = {"action": "run_metric", "target": "big_breakdown", "result": result}
    spec = build_chart_spec(step)
    assert len(spec["data"]["values"]) == 50
    assert "_note" in spec