"""P0 planner reliability tests — deterministic routes for common analytics intents."""

import pandas as pd
import pytest

from data_source import DataSource
from agent_phase2 import _forced_plan_from_question


def _ds():
    ds = DataSource()
    df = pd.DataFrame({
        "region": ["South", "West", "North", "East"],
        "sales": [4375.5, 3730.0, 2670.0, 2615.0],
        "category": ["Electronics", "Furniture", "Electronics", "Furniture"],
    })
    ds.load_dataframe(df)
    return ds


def test_force_total_sales_plan():
    p = _forced_plan_from_question("what is total revenue?", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "single_metric"
    assert p.steps[0].action == "run_metric"


def test_force_total_sales_plan_synonym():
    p = _forced_plan_from_question("what is total sales?", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "single_metric"


def test_force_describe():
    p = _forced_plan_from_question("describe the data", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "describe"


def test_force_row_count():
    p = _forced_plan_from_question("how many rows are in the dataset", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "describe"


def test_force_outliers():
    p = _forced_plan_from_question("are there any outliers in sales?", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "anomaly_detect"


def test_force_breakdown_by_region():
    p = _forced_plan_from_question("break down sales by region", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["group_col"] == "region"
    assert p.steps[0].args["value_col"] == "sales"


def test_force_breakdown_by_category():
    p = _forced_plan_from_question("breakdown by category", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["group_col"] == "category"


def test_no_forced_plan_for_unrelated_question():
    p = _forced_plan_from_question("what is the weather like?", _ds())
    assert p is None