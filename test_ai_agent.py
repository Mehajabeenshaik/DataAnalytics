import json
from unittest.mock import MagicMock, patch

import pandas as pd

from ai_agent import (
    select_metric,
    ask,
    run_metric,
    scrub_results,
    explain,
    MetricSelection,
)


def make_mock_provider(response_json: dict):
    provider = MagicMock()
    provider.generate.return_value = json.dumps(response_json)
    return provider


# ── select_metric tests ──────────────────────────────────────────────────

def test_matching_metric_routes_correctly():
    provider = make_mock_provider({"metric_name": "total_revenue", "filters": {}, "no_match": False})
    selection = select_metric("what's our total revenue?", provider)
    assert selection.metric_name == "total_revenue"
    assert selection.no_match is False


def test_unmatched_question_returns_no_match():
    provider = make_mock_provider({"no_match": True})
    selection = select_metric("what's the weather like?", provider)
    assert selection.no_match is True
    assert selection.metric_name is None


def test_hallucinated_metric_name_is_rejected():
    # LLM invents a metric that isn't in the allowlist — must be stripped, not trusted
    provider = make_mock_provider({"metric_name": "customer_lifetime_value", "filters": {}, "no_match": False})
    selection = select_metric("what's CLV?", provider)
    assert selection.metric_name is None  # rejected by the validator


def test_non_allowlisted_filter_is_stripped():
    """Filter keys not in ALLOWED_FILTER_COLUMNS must be stripped, not trusted."""
    provider = make_mock_provider({
        "metric_name": "total_revenue",
        "filters": {"order_status": "completed", "malicious_column": "drop table"},
        "no_match": False,
    })
    selection = select_metric("what's our total revenue?", provider)
    assert "malicious_column" not in selection.filters
    assert "order_status" in selection.filters


def test_malformed_llm_response_returns_no_match():
    """Garbage JSON from the LLM should degrade to no_match, never a guess."""
    provider = MagicMock()
    provider.generate.return_value = "this is not json at all"
    selection = select_metric("what's our total revenue?", provider)
    assert selection.no_match is True
    assert selection.metric_name is None


# ── ask() end-to-end tests ────────────────────────────────────────────────

def test_ask_end_to_end_no_match():
    provider = make_mock_provider({"no_match": True})
    result = ask("do you sell rockets?", provider)
    assert result["metric_used"] is None
    assert "don't have a defined metric" in result["answer"]


def test_ask_end_to_end_happy_path():
    """Full ask() flow: metric selected → run_metric → explain → result dict."""
    provider = MagicMock()
    # First call: select_metric returns a matching metric
    # Second call: explain returns a valid explanation
    provider.generate.side_effect = [
        json.dumps({"metric_name": "total_revenue", "filters": {}, "no_match": False}),
        json.dumps({"answer": "Total revenue is Rs 12.1 crore.", "confidence": "high", "caveat": None}),
    ]
    result = ask("what is our total revenue?", provider)
    assert result["metric_used"] == "total_revenue"
    assert "revenue" in result["answer"].lower()
    assert result["confidence"] in ("high", "low")
    assert result["filters_used"] == {}


# ── run_metric tests (deterministic, no LLM) ──────────────────────────────

def test_run_metric_total_revenue():
    """run_metric with total_revenue should return a positive number."""
    result = run_metric("total_revenue", {})
    assert isinstance(result, (int, float))
    assert result > 0


def test_run_metric_revenue_by_region():
    """run_metric with revenue_by_region should return a Series grouped by region."""
    result = run_metric("revenue_by_region", {})
    assert isinstance(result, pd.Series)
    assert len(result) > 0


def test_run_metric_order_count():
    """run_metric with order_count should return a positive number."""
    result = run_metric("order_count", {})
    assert isinstance(result, (int, float))
    assert result > 0


def test_run_metric_avg_order_value():
    """run_metric with avg_order_value should return a positive number."""
    result = run_metric("avg_order_value", {})
    assert isinstance(result, (int, float))
    assert result > 0


def test_run_metric_refund_rate():
    """run_metric with refund_rate should return a number between 0 and 100."""
    result = run_metric("refund_rate", {})
    assert isinstance(result, (int, float))
    assert 0 <= result <= 100


def test_run_metric_with_filter():
    """run_metric should respect user-supplied filters."""
    result_no_filter = run_metric("total_revenue", {})
    result_filtered = run_metric("total_revenue", {"customer_region": "North"})
    # Filtered result should be <= unfiltered (subset of data)
    assert result_filtered <= result_no_filter


# ── scrub_results tests ───────────────────────────────────────────────────

def test_scrub_results_passes_through_numbers():
    """Numbers should pass through scrub_results untouched."""
    assert scrub_results(42) == 42
    assert scrub_results(3.14) == 3.14


def test_scrub_results_passes_through_series():
    """Series should pass through scrub_results untouched."""
    s = pd.Series([100, 200, 300])
    result = scrub_results(s)
    assert result is s


def test_scrub_results_redacts_pii_string():
    """Strings with detected PII should be redacted."""
    with patch("ai_agent.PIIMasker") as MockMasker:
        mock_instance = MockMasker.return_value
        mock_instance.scan_text.return_value = [{"entity_type": "EMAIL"}]
        result = scrub_results("Contact me at john@example.com")
        assert "REDACTED" in result


def test_scrub_results_passes_clean_string():
    """Strings without PII should pass through untouched."""
    with patch("ai_agent.PIIMasker") as MockMasker:
        mock_instance = MockMasker.return_value
        mock_instance.scan_text.return_value = []
        result = scrub_results("hello world")
        assert result == "hello world"


# ── explain tests ─────────────────────────────────────────────────────────

def test_explain_downgrades_confidence_for_small_series():
    """explain() should downgrade 'high' confidence to 'low' for small result sets."""
    provider = make_mock_provider({
        "answer": "Revenue by region shows North leading.",
        "confidence": "high",
        "caveat": None,
    })
    # Small series: only 2 elements (< 3 threshold)
    small_series = pd.Series([100, 200], index=["North", "South"])
    result = explain("revenue by region", "revenue_by_region", small_series, provider)
    assert result.confidence == "low"
    assert "Small result set" in (result.caveat or "")


def test_explain_preserves_high_confidence_for_large_series():
    """explain() should preserve 'high' confidence for larger result sets."""
    provider = make_mock_provider({
        "answer": "Revenue by region shows North leading.",
        "confidence": "high",
        "caveat": None,
    })
    # Large series: 4 elements (>= 3 threshold)
    large_series = pd.Series([100, 200, 300, 400], index=["North", "South", "East", "West"])
    result = explain("revenue by region", "revenue_by_region", large_series, provider)
    assert result.confidence == "high"


def test_explain_handles_malformed_llm_response():
    """If the LLM returns garbage, explain() should fall back to a low-confidence answer."""
    provider = MagicMock()
    provider.generate.return_value = "not valid json"
    result = explain("what is revenue?", "total_revenue", 50000, provider)
    assert result.confidence == "low"
    assert result.caveat is not None