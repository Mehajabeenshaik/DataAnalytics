"""test_cache.py - Tests for the TTL-based response cache."""
import json
import os
os.environ.setdefault("JWT_SECRET_KEY", "pytest-test-secret-not-for-production-7f3a9b2e")

from unittest.mock import MagicMock
import pandas as pd
import pytest
from data_source import DataSource
from agent_phase2 import ask
from cache import clear_cache, get_cached_response, set_cached_response, cache_info


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "order_id": [1, 2, 3, 4, 5, 6],
        "revenue": [100.0, 200.0, 300.0, 150.0, 250.0, 400.0],
        "quantity": [1, 2, 3, 1, 2, 4],
        "region": ["North", "South", "North", "East", "West", "South"],
        "category": ["A", "B", "A", "C", "B", "A"],
    })


@pytest.fixture
def ds(sample_df):
    ds = DataSource()
    ds.load_dataframe(sample_df)
    return ds


@pytest.fixture(autouse=True)
def clean_cache():
    clear_cache()
    yield
    clear_cache()


def test_cache_hit_skips_llm(ds):
    """Calling ask() twice with the same question should only call the LLM once."""
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({
            "can_answer": True,
            "reason": "Found",
            "plan_type": "single_metric",
            "steps": [{"step_id": 1, "action": "run_metric", "target": first_metric, "filters": {}, "args": {}}],
        }),
        json.dumps({"answer": "Result.", "confidence": "high", "caveats": [], "lineage": {"metrics_or_tools_used": [first_metric], "filters_applied": {}, "notes": "6 rows"}}),
    ]
    # First call - cache miss, should call LLM
    result1 = ask("What is total revenue?", ds, provider)
    assert provider.generate.call_count == 2  # planner + synthesizer
    assert result1.get("cached") is not True  # not from cache

    # Second call - cache hit, should NOT call LLM
    result2 = ask("What is total revenue?", ds, provider)
    assert provider.generate.call_count == 2  # still 2, no new calls
    assert result2.get("cached") is True  # from cache


def test_cache_normalization(ds):
    """Different phrasing of the same question should hit the same cache entry."""
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({"can_answer": True, "reason": "Found", "plan_type": "single_metric", "steps": [{"step_id": 1, "action": "run_metric", "target": first_metric, "filters": {}, "args": {}}]}),
        json.dumps({"answer": "Result.", "confidence": "high", "caveats": [], "lineage": {"metrics_or_tools_used": [first_metric], "filters_applied": {}, "notes": "6 rows"}}),
    ]
    # First call with "Total revenue?"
    ask("Total revenue?", ds, provider)
    # Second call with "total revenue" (no question mark, different case)
    result2 = ask("total revenue", ds, provider)
    assert result2.get("cached") is True
    assert provider.generate.call_count == 2  # only first call hit LLM


def test_no_match_not_cached(ds):
    """no_match responses should NOT be cached."""
    provider = MagicMock()
    provider.generate.return_value = json.dumps({"can_answer": False, "reason": "No match", "plan_type": "no_match", "steps": []})
    # First call - no_match
    result1 = ask("What is the weather?", ds, provider)
    assert result1.get("cached") is not True
    # Second call - should call LLM again (not cached)
    result2 = ask("What is the weather?", ds, provider)
    assert result2.get("cached") is not True
    assert provider.generate.call_count == 2  # called LLM both times


def test_clear_cache(ds):
    """clear_cache() should empty the cache."""
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({"can_answer": True, "reason": "Found", "plan_type": "single_metric", "steps": [{"step_id": 1, "action": "run_metric", "target": first_metric, "filters": {}, "args": {}}]}),
        json.dumps({"answer": "Result.", "confidence": "high", "caveats": [], "lineage": {"metrics_or_tools_used": [first_metric], "filters_applied": {}, "notes": "6 rows"}}),
    ]
    ask("What is total revenue?", ds, provider)
    assert cache_info()["size"] > 0
    clear_cache()
    assert cache_info()["size"] == 0


def test_cache_info():
    """cache_info() should return stats."""
    info = cache_info()
    assert "size" in info
    assert "maxsize" in info
    assert "ttl" in info
    assert info["maxsize"] == 500


def test_cache_does_not_leak_across_datasets():
    """Two DataSources with different data, same question text, must NOT
    return the same cached result (regression test for cross-tenant leak)."""
    df_a = pd.DataFrame({
        "order_id": [1, 2, 3],
        "revenue": [100.0, 200.0, 300.0],
        "region": ["North", "South", "North"],
    })
    df_b = pd.DataFrame({
        "order_id": [1, 2, 3],
        "revenue": [9000.0, 9000.0, 9000.0],
        "region": ["East", "West", "East"],
    })
    ds_a = DataSource()
    ds_a.load_dataframe(df_a)
    ds_b = DataSource()
    ds_b.load_dataframe(df_b)

    metric_a = list(ds_a.get_metrics().keys())[0]
    metric_b = list(ds_b.get_metrics().keys())[0]

    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({"can_answer": True, "reason": "Found", "plan_type": "single_metric",
                    "steps": [{"step_id": 1, "action": "run_metric", "target": metric_a, "filters": {}, "args": {}}]}),
        json.dumps({"answer": "Dataset A result.", "confidence": "high", "caveats": [], "lineage": {}}),
        json.dumps({"can_answer": True, "reason": "Found", "plan_type": "single_metric",
                    "steps": [{"step_id": 1, "action": "run_metric", "target": metric_b, "filters": {}, "args": {}}]}),
        json.dumps({"answer": "Dataset B result.", "confidence": "high", "caveats": [], "lineage": {}}),
    ]

    result_a = ask("What is total revenue?", ds_a, provider)
    result_b = ask("What is total revenue?", ds_b, provider)

    assert result_a["answer"] != result_b["answer"]
    assert provider.generate.call_count == 4  # both datasets hit the LLM, no false cache hit
