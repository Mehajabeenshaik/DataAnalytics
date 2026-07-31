import json
from unittest.mock import MagicMock
from ai_agent import select_metric, ask, MetricSelection


def make_mock_provider(response_json: dict):
    provider = MagicMock()
    provider.generate.return_value = json.dumps(response_json)
    return provider


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


def test_ask_end_to_end_no_match():
    provider = make_mock_provider({"no_match": True})
    result = ask("do you sell rockets?", provider)
    assert result["metric_used"] is None
    assert "don't have a defined metric" in result["answer"]