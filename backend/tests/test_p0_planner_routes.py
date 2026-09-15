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


# ── Categorical-VALUE routing (filtered / share / comparison) ─────────────
#
# Regression cover for the bug where a category-filtered question had no tool
# to reach for and silently returned an UNFILTERED total: "How many orders are
# in the Electronics category?" answered 4 (the whole table) instead of 2.

def test_force_filtered_count_by_category_value():
    p = _forced_plan_from_question("how many orders are in the Electronics category?", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "categorical_filtered_agg"
    assert p.steps[0].args["agg"] == "count"
    assert p.steps[0].args["filter_col"] == "category"
    assert p.steps[0].args["filter_value"] == "Electronics"


def test_force_filtered_sum_and_mean_by_value():
    p = _forced_plan_from_question("total sales in the West region", _ds())
    assert p is not None and p.can_answer
    assert p.steps[0].args["agg"] == "sum"
    assert p.steps[0].args["filter_value"] == "West"

    p2 = _forced_plan_from_question("average sales in North", _ds())
    assert p2 is not None and p2.can_answer
    assert p2.steps[0].args["agg"] == "mean"
    assert p2.steps[0].args["filter_value"] == "North"


def test_force_filtered_agg_refuses_unknown_value():
    """A value that does not exist must refuse — never an unfiltered total."""
    p = _forced_plan_from_question("how many orders are in the Furniture-XL category?", _ds())
    assert p is not None
    assert p.can_answer is False
    assert p.plan_type == "no_match"
    assert "no such filter value" in p.reason


def test_partial_value_word_is_not_a_match():
    """'Furniture' inside 'Furniture-XL' must not be treated as the value."""
    p = _forced_plan_from_question("how many orders are in the Furniture-XL category?", _ds())
    assert p.can_answer is False


def test_force_two_entity_comparison_uses_only_named_values():
    """'in North higher than in South' must not surface West/East at all."""
    p = _forced_plan_from_question("is average sales in North higher than in South", _ds())
    assert p is not None and p.can_answer
    assert len(p.steps) == 2
    assert all(s.target == "categorical_filtered_agg" for s in p.steps)
    assert all(s.args["agg"] == "mean" for s in p.steps)
    assert [s.args["filter_value"] for s in p.steps] == ["North", "South"]
    assert all(s.args["filter_col"] == "region" for s in p.steps)


def test_force_percentage_of_total():
    p = _forced_plan_from_question("What percentage of total sales came from Electronics?", _ds())
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "percentage_of_total"
    assert p.steps[0].args["filter_col"] == "category"
    assert p.steps[0].args["filter_value"] == "Electronics"


def test_force_share_wording_variants():
    for q in ("what share of total sales is from Electronics?",
              "proportion of total sales from North"):
        p = _forced_plan_from_question(q, _ds())
        assert p is not None and p.can_answer, q
        assert p.steps[0].target == "percentage_of_total", q


def _ds_with_dates():
    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "order_date": pd.to_datetime([
            "2024-01-05", "2024-01-20", "2024-02-11", "2024-03-02",
        ]),
        "region": ["North", "South", "North", "West"],
        "sales": [100.0, 200.0, 300.0, 400.0],
    }))
    return ds


def test_month_filter_route_still_wins_for_month_questions():
    """The value-filter route must not hijack month-filtered totals."""
    p = _forced_plan_from_question("Total sales in January by region", _ds_with_dates())
    assert p is not None and p.can_answer
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["month"] == 1
    assert "date_col" in p.steps[0].args


def test_month_total_keeps_its_filter():
    p = _forced_plan_from_question("total sales in January", _ds_with_dates())
    assert p is not None and p.can_answer
    assert p.steps[0].target == "filtered_agg"
    assert p.steps[0].args["month"] == 1


def test_value_routing_does_not_break_breakdowns():
    """'break down sales by region' stays a group_compare breakdown."""
    p = _forced_plan_from_question("break down sales by region", _ds())
    assert p is not None and p.can_answer
    assert p.steps[0].target == "group_compare"


# ── End-to-end on the shipped sample dataset (reviewer's repro) ──────────

def _sample_ds():
    from pathlib import Path

    sample = Path(__file__).resolve().parents[2] / "samples" / "sample_sales_data.csv"
    if not sample.exists():
        pytest.skip(f"sample dataset missing: {sample}")
    ds = DataSource(name="sample_sales_data")
    ds.load_file(str(sample))
    return ds


def test_sample_dataset_electronics_count_is_7_not_20():
    """"How many orders are in the Electronics category?" must be 7 of 20."""
    from stats_tools import run_stats_tool

    ds = _sample_ds()
    assert ds.profile.n_rows == 20

    plan = _forced_plan_from_question(
        "How many orders are in the Electronics category?", ds
    )
    assert plan is not None and plan.can_answer
    step = plan.steps[0]
    assert step.target == "categorical_filtered_agg"

    answer = run_stats_tool(ds, step.target, step.args)
    assert answer == 7
    assert answer != ds.profile.n_rows


def test_sample_dataset_unknown_category_value_declines():
    ds = _sample_ds()
    plan = _forced_plan_from_question(
        "How many orders are in the Furniture-XL category?", ds
    )
    assert plan is not None and plan.can_answer is False


def test_sample_dataset_electronics_share_is_about_71_percent():
    """'% of total sales from Electronics' == 9570 / 13390.5 ~= 71.47%."""
    from stats_tools import run_stats_tool

    ds = _sample_ds()
    plan = _forced_plan_from_question(
        "What percentage of total sales came from Electronics?", ds
    )
    assert plan is not None and plan.can_answer
    step = plan.steps[0]
    assert step.target == "percentage_of_total"

    share = run_stats_tool(ds, step.target, step.args)
    assert share == pytest.approx(71.47, abs=0.05)


def test_sample_dataset_north_vs_south_comparison_excludes_other_regions():
    """The comparison must reference only the two named regions."""
    ds = _sample_ds()
    plan = _forced_plan_from_question(
        "is average sales in North higher than in South", ds
    )
    assert plan is not None and plan.can_answer
    values = [s.args["filter_value"] for s in plan.steps]
    assert values == ["North", "South"]
    for other in ("West", "East"):
        assert other not in values

    from stats_tools import run_stats_tool

    means = {s.args["filter_value"]: run_stats_tool(ds, s.target, s.args) for s in plan.steps}
    assert means["South"] > means["North"]