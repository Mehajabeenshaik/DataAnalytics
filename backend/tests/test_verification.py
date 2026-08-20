"""
Phase 6 tests — computed confidence & verification sanity checks.

These tests exercise verify_answer() directly (no LLM, no pipeline), covering:
  - clean exact metric match          -> high confidence, no flags
  - count result exceeding source rows -> flagged, low confidence
  - malformed synthesizer fallback     -> forced low regardless of LLM claim
  - negative money-like value          -> flagged, low confidence
  - breakdown vs total > 1% mismatch   -> flagged, low confidence
  - truncated result set              -> flagged, never high
"""

from verification import verify_answer


class FakePlan:
    plan_type = "single_metric"


class StatsPlan:
    plan_type = "stats_tool"


def test_clean_exact_match_is_high():
    results = [{"target": "total_revenue", "result": 1400.0, "error": None}]
    v = verify_answer(FakePlan(), results, {})
    assert v["computed_confidence"] == "high"
    assert v["flags"] == []


def test_count_exceeding_rows_flagged():
    results = [{"target": "row_count", "result": 999, "error": None, "_source_row_count": 20}]
    v = verify_answer(FakePlan(), results, {})
    assert "count_exceeds_row_count:row_count" in v["flags"]
    assert v["computed_confidence"] == "low"


def test_count_within_rows_not_flagged():
    results = [{"target": "row_count", "result": 20, "error": None, "_source_row_count": 20}]
    v = verify_answer(FakePlan(), results, {})
    assert v["flags"] == []
    assert v["computed_confidence"] == "high"


def test_malformed_response_forces_low():
    results = [{"target": "total_revenue", "result": 1400.0, "error": None}]
    v = verify_answer(FakePlan(), results, {"_parse_failed": True})
    assert v["computed_confidence"] == "low"
    assert v["passed"] is False


def test_negative_revenue_flagged():
    results = [{"target": "total_revenue", "result": -500.0, "error": None}]
    v = verify_answer(FakePlan(), results, {})
    assert "unexpected_negative:total_revenue" in v["flags"]
    assert v["computed_confidence"] == "low"


def test_negative_unrelated_column_not_flagged():
    # Heuristic applies only to revenue/sales/price/amount/quantity-like targets.
    results = [{"target": "temperature_anomaly", "result": -500.0, "error": None}]
    v = verify_answer(FakePlan(), results, {})
    assert v["flags"] == []
    assert v["computed_confidence"] == "high"


def test_breakdown_total_mismatch_flagged():
    results = [
        {
            "target": "sales_by_region",
            "result": {"North": 100.0, "South": 200.0},
            "error": None,
            "_breakdown": {"North": 100.0, "South": 200.0},
            "_expected_total": 400.0,  # sum 300 != 400 -> >1% mismatch
        }
    ]
    v = verify_answer(StatsPlan(), results, {})
    assert "breakdown_total_mismatch:sales_by_region" in v["flags"]
    assert v["computed_confidence"] == "low"


def test_breakdown_total_within_one_percent_not_flagged():
    results = [
        {
            "target": "sales_by_region",
            "result": {"North": 100.0, "South": 200.0},
            "error": None,
            "_breakdown": {"North": 100.0, "South": 200.0},
            "_expected_total": 300.0,
        }
    ]
    v = verify_answer(Stats(), results, {})
    assert v["flags"] == []
    assert v["computed_confidence"] == "medium"  # stats-tool run, not catalog hit


def test_truncated_result_never_high():
    results = [{"target": "describe", "result": [], "error": None, "_truncated": True}]
    v = verify_answer(Stats(), results, {})
    assert "result_truncated:describe" in v["flags"]
    assert v["computed_confidence"] == "low"


def test_execution_error_low():
    results = [{"target": "total_revenue", "result": None, "error": "Column not found"}]
    v = verify_answer(FakePlan(), results, {})
    assert v["computed_confidence"] == "low"
    assert v["passed"] is False


def test_passed_flag():
    v = verify_answer(FakePlan(), [{"target": "total_revenue", "result": 1.0, "error": None}], {})
    assert v["passed"] is True
    v = verify_answer(
        FakePlan(),
        [{"target": "row_count", "result": 5, "error": None, "_source_row_count": 3}],
        {},
    )
    assert v["passed"] is False


class Stats:
    plan_type = "stats_tool"