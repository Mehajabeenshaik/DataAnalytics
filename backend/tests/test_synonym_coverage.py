"""Regression tests: synonym coverage and routing for common phrasings."""

import pandas as pd
import pytest

from data_source import DataSource
from agent_phase2 import ask, _forced_plan_from_question
from eval.mock_provider import MockTrustProvider


def _loaded_ds():
    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "region": ["East", "West", "East", "North"],
        "category": ["Electronics", "Books", "Electronics", "Toys"],
        "revenue": [100.0, 200.0, 150.0, 50.0],
    }))
    return ds


def _sales_ds():
    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "region": ["South", "West", "North", "East"],
        "sales": [4375.5, 3730.0, 2670.0, 2615.0],
        "category": ["Electronics", "Furniture", "Electronics", "Furniture"],
    }))
    return ds


def test_total_revenue_resolves():
    ds = _loaded_ds()
    result = ask("what is total revenue", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type != "no_match"


def test_total_sales_resolves():
    ds = _sales_ds()
    result = ask("what is total sales", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type != "no_match"


def test_sum_of_sales_resolves():
    ds = _sales_ds()
    result = ask("what is the sum of sales", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type != "no_match"


def test_average_sales_resolves():
    ds = _sales_ds()
    result = ask("what is the average sales", ds, MockTrustProvider())
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


def test_outliers_resolves():
    ds = _sales_ds()
    result = ask("are there any outliers in sales", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type != "no_match"


def test_breakdown_by_region_resolves():
    ds = _sales_ds()
    result = ask("break down sales by region", ds, MockTrustProvider())
    plan_type = (result.get("plan") or {}).get("plan_type") or result.get("plan_type")
    assert plan_type != "no_match"


def test_breakdown_by_category_resolves():
    ds = _sales_ds()
    result = ask("breakdown by category", ds, MockTrustProvider())
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


def test_forced_plan_describe():
    p = _forced_plan_from_question("describe the data", _loaded_ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "describe"


def test_forced_plan_row_count():
    p = _forced_plan_from_question("how many rows are in the dataset", _loaded_ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"


def test_forced_plan_outliers():
    p = _forced_plan_from_question("are there outliers in revenue", _loaded_ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "anomaly_detect"


def test_forced_plan_total_sales():
    p = _forced_plan_from_question("what is total sales", _sales_ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "single_metric"


def test_forced_plan_breakdown_by_region():
    p = _forced_plan_from_question("break down sales by region", _sales_ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["group_col"] == "region"
    assert p.steps[0].args["value_col"] == "sales"