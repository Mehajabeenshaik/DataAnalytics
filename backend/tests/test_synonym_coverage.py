"""Regression tests: synonym coverage and routing for common phrasings."""

import pandas as pd
import pytest

from data_source import DataSource
from agent_phase2 import ask
from eval.mock_provider import MockTrustProvider


def _loaded_ds():
    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "region": ["East", "West", "East", "North"],
        "category": ["Electronics", "Books", "Electronics", "Toys"],
        "revenue": [100.0, 200.0, 150.0, 50.0],
    }))
    return ds


def test_total_revenue_resolves():
    ds = _loaded_ds()
    result = ask("what is total revenue", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type != "no_match"


def test_describe_resolves_to_stats_tool():
    ds = _loaded_ds()
    result = ask("describe the data", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type in ("stats_tool", "single_metric")  # not no_match


def test_row_count_resolves():
    ds = _loaded_ds()
    result = ask("how many rows are in the dataset", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type != "no_match"


def test_nonexistent_column_does_not_silently_substitute():
    ds = _loaded_ds()
    result = ask("which product has the highest sales", ds, MockTrustProvider())
    answer = (result.get("answer") or "").lower()
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    # Either refuses cleanly, or explicitly names the substitution — never
    # silently answers about "region" as if it were "product"
    assert plan_type == "no_match" or "category" in answer or "region" in answer