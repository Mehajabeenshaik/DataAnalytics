"""P0.5 analyst routing reliability tests.

Covers the three live-demo failures:
  1. "Average customer_rating by region" must mean-aggregate customer_rating
     by region (NOT a sales sum).
  2. "Total sales in January" must apply the month filter (filtered_agg,
     month=1 → ~6040.5 on the sample), never the unfiltered grand total
     (13390.5) at high confidence.
  3. "product" questions must refuse (no_match) when no product column exists.
"""

from pathlib import Path

import pandas as pd
import pytest

from data_source import DataSource
from agent_phase2 import (
    _forced_plan_from_question,
    _forced_group_agg,
    _forced_month_total,
    _parse_month,
    execute_plan,
)
from stats_tools import filtered_agg, run_stats_tool
from verification import verify_answer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_CSV = _REPO_ROOT / "sample_sales_data.csv"

JAN_TOTAL = 6040.50   # sum of sales for 2024-01 rows in sample_sales_data.csv
FULL_TOTAL = 13390.50  # sum of ALL sales rows in sample_sales_data.csv


def _ds_with_dates():
    """DataSource loaded from the repo sample CSV (has date/region/rating)."""
    ds = DataSource()
    ds.load_file(str(_SAMPLE_CSV))
    return ds


def _ds_simple():
    """Minimal dataset matching test_p0_planner_routes.py (no date column)."""
    ds = DataSource()
    df = pd.DataFrame({
        "region": ["South", "West", "North", "East"],
        "sales": [4375.5, 3730.0, 2670.0, 2615.0],
        "category": ["Electronics", "Furniture", "Electronics", "Furniture"],
    })
    ds.load_dataframe(df)
    return ds


# ── A) avg VALUE by GROUP forced plan ─────────────────────────────────────

def test_avg_rating_by_region_plan():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("Average customer_rating by region", ds)
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["value_col"] == "customer_rating"
    assert p.steps[0].args["group_col"] == "region"
    assert p.steps[0].args["agg"] == "mean"


def test_avg_rating_by_region_executes_mean_not_sales_sum():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("Average customer_rating by region", ds)
    results = execute_plan(p, ds)
    assert not results[0].get("error"), results[0].get("error")
    series = results[0]["result"]
    # Mean rating per region must be between 1 and 5 — a sales sum would not be.
    for v in series.values:
        assert 1.0 <= float(v) <= 5.0


def test_total_sales_by_category_still_sum():
    ds = _ds_simple()
    p = _forced_plan_from_question("total sales by category", ds)
    assert p is not None and p.can_answer
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["value_col"] == "sales"
    assert p.steps[0].args["agg"] == "sum"


def test_forced_group_agg_helper_direct():
    ds = _ds_with_dates()
    p = _forced_group_agg("average rating by region", ds)
    assert p is not None
    assert p.steps[0].args["agg"] == "mean"
    assert p.steps[0].args["value_col"] == "customer_rating"


# ── B) month-filtered totals ──────────────────────────────────────────────

def test_parse_month_names_and_abbrs():
    assert _parse_month("Total sales in January") == 1
    assert _parse_month("sales for feb") == 2
    assert _parse_month("revenue in December") == 12
    assert _parse_month("total in 2024-03") == 3
    assert _parse_month("total sales") is None


def test_january_total_plan_uses_filtered_agg():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("Total sales in January", ds)
    assert p is not None and p.can_answer
    assert p.plan_type == "stats_tool"
    assert p.steps[0].target == "filtered_agg"
    assert p.steps[0].args["month"] == 1
    assert p.steps[0].args["value_col"] == "sales"
    assert p.steps[0].args["date_col"] == "date"


def test_january_total_not_full_year():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("Total sales in January", ds)
    results = execute_plan(p, ds)
    assert not results[0].get("error"), results[0].get("error")
    val = float(results[0]["result"])
    assert val == pytest.approx(JAN_TOTAL, abs=0.01)
    assert val != pytest.approx(FULL_TOTAL, abs=0.01)


def test_february_total():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("total sales in February", ds)
    results = execute_plan(p, ds)
    assert not results[0].get("error")
    assert float(results[0]["result"]) == pytest.approx(FULL_TOTAL - JAN_TOTAL, abs=0.01)


def test_month_total_without_date_column_refuses():
    # Dataset has sales but NO date column: month filter cannot be applied.
    ds = _ds_simple()
    p = _forced_plan_from_question("total sales in January", ds)
    assert p is not None
    assert p.plan_type == "no_match"
    assert not p.can_answer


def test_filtered_agg_tool_direct():
    ds = _ds_with_dates()
    val = filtered_agg(ds, "sales", agg="sum", date_col="date", month=1)
    assert val == pytest.approx(JAN_TOTAL, abs=0.01)


def test_filtered_agg_no_rows_raises():
    ds = _ds_with_dates()
    with pytest.raises(ValueError):
        filtered_agg(ds, "sales", agg="sum", date_col="date", month=7)


def test_filtered_agg_via_dispatcher():
    ds = _ds_with_dates()
    val = run_stats_tool(
        ds, "filtered_agg",
        {"value_col": "sales", "agg": "sum", "date_col": "date", "month": 1},
    )
    assert val == pytest.approx(JAN_TOTAL, abs=0.01)


# ── C) product guard ──────────────────────────────────────────────────────

def test_product_question_no_match_without_product_col():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("which product sells the most?", ds)
    assert p is not None
    assert p.plan_type == "no_match"
    assert not p.can_answer
    assert "product" in p.reason.lower()


def test_product_question_ok_with_product_col():
    ds = DataSource()
    df = pd.DataFrame({
        "product": ["A", "B", "A"],
        "sales": [10.0, 20.0, 30.0],
    })
    ds.load_dataframe(df)
    p = _forced_plan_from_question("total sales by product", ds)
    assert p is not None and p.can_answer


# ── D) verification month guard ───────────────────────────────────────────

def test_verification_flags_missing_month_filter():
    from agent_phase2 import Plan, PlanStep

    ds = _ds_with_dates()
    # Simulate the OLD bug: month question answered with an UNFILTERED total.
    plan = Plan(
        can_answer=True,
        reason="total_sum_metric",
        plan_type="single_metric",
        steps=[PlanStep(step_id=1, action="run_metric", target="total_sales")],
    )
    results = [{
        "step_id": 1, "action": "run_metric", "target": "total_sales",
        "filters": {}, "args": {}, "result": FULL_TOTAL, "error": None,
    }]
    synth = {"answer": "13390.5", "confidence": "high", "caveats": [], "lineage": {}}
    v = verify_answer(plan, results, synth, question="Total sales in January")
    assert "time_filter_not_applied" in v["flags"]
    assert v["computed_confidence"] == "low"


def test_verification_passes_with_month_filter_applied():
    from agent_phase2 import Plan, PlanStep

    ds = _ds_with_dates()
    plan = Plan(
        can_answer=True,
        reason="filtered_agg",
        plan_type="stats_tool",
        steps=[PlanStep(
            step_id=1, action="run_stats", target="filtered_agg",
            filters={},
            args={"value_col": "sales", "agg": "sum", "date_col": "date", "month": 1},
        )],
    )
    results = [{
        "step_id": 1, "action": "run_stats", "target": "filtered_agg",
        "filters": {},
        "args": {"value_col": "sales", "agg": "sum", "date_col": "date", "month": 1},
        "result": JAN_TOTAL, "error": None,
    }]
    synth = {"answer": "6040.5", "confidence": "high", "caveats": [], "lineage": {}}
    v = verify_answer(plan, results, synth, question="Total sales in January")
    assert "time_filter_not_applied" not in v["flags"]


def test_verification_no_month_no_flag():
    from agent_phase2 import Plan, PlanStep

    plan = Plan(
        can_answer=True, reason="total", plan_type="single_metric",
        steps=[PlanStep(step_id=1, action="run_metric", target="total_sales")],
    )
    results = [{
        "step_id": 1, "action": "run_metric", "target": "total_sales",
        "filters": {}, "args": {}, "result": FULL_TOTAL, "error": None,
    }]
    synth = {"answer": "13390.5", "confidence": "high", "caveats": [], "lineage": {}}
    v = verify_answer(plan, results, synth, question="what is total sales?")
    assert "time_filter_not_applied" not in v["flags"]


# ── E) regression: existing routes unchanged ─────────────────────────────

def test_plain_total_sales_still_single_metric():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("what is total sales?", ds)
    assert p is not None and p.can_answer
    assert p.plan_type == "single_metric"


def test_breakdown_by_region_still_works():
    ds = _ds_simple()
    p = _forced_plan_from_question("break down sales by region", ds)
    assert p is not None and p.can_answer
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["group_col"] == "region"
    assert p.steps[0].args["value_col"] == "sales"


# ── F) month + group together ─────────────────────────────────────────────

def test_january_sales_by_region_keeps_month_filter():
    ds = _ds_with_dates()
    p = _forced_plan_from_question("Total sales in January by region", ds)
    assert p is not None and p.can_answer
    assert p.steps[0].target == "group_compare"
    assert p.steps[0].args["month"] == 1
    assert p.steps[0].args["value_col"] == "sales"
    assert p.steps[0].args["group_col"] == "region"
    results = execute_plan(p, ds)
    assert not results[0].get("error"), results[0].get("error")
    series = results[0]["result"]
    assert float(series.sum()) == pytest.approx(JAN_TOTAL, abs=0.01)


def test_verification_accepts_grouped_month_filter():
    from agent_phase2 import Plan, PlanStep

    plan = Plan(
        can_answer=True, reason="group+month", plan_type="stats_tool",
        steps=[PlanStep(
            step_id=1, action="run_stats", target="group_compare",
            args={"value_col": "sales", "group_col": "region", "agg": "sum",
                  "date_col": "date", "month": 1},
        )],
    )
    results = [{
        "step_id": 1, "action": "run_stats", "target": "group_compare",
        "args": {"value_col": "sales", "group_col": "region", "month": 1},
        "result": {"North": 1}, "error": None,
    }]
    v = verify_answer(plan, results, {"answer": "ok", "confidence": "high", "caveats": [], "lineage": {}},
                      question="Total sales in January by region")
    assert "time_filter_not_applied" not in v["flags"]