"""Mock-provider answer synthesis must not leak internals (regression).

Under LLM_PROVIDER=mock, answers used to read
    "Based on the data, the key result is 1, 13,390.50 (mock)."
i.e. a stray JSON field/step index ("1") and a dev-only "(mock)" marker leaked
into user-facing text. The synthesizer now parses the Results block as JSON and
renders only each entry's `result` value.
"""

import io
import json

import pandas as pd
import pytest

from data_source import DataSource
from eval.mock_provider import (
    MockTrustProvider,
    _fmt_num,
    _render_result,
    _result_label,
)
from agent_phase4 import run_governed_ask

SALES_CSV = (
    "order_id,region,category,sales\n"
    "ORD-1001,North,Electronics,100.0\n"
    "ORD-1002,South,Furniture,200.0\n"
    "ORD-1003,North,Electronics,300.0\n"
)


def _prompt(entries):
    return "Question: q\n\nPlan: {}\n\nResults:\n" + json.dumps(entries, indent=2)


def _synthesize_answer(entries):
    raw = MockTrustProvider()._synthesize(_prompt(entries))
    return json.loads(raw)["answer"]


# ── Formatting helpers ───────────────────────────────────────────────────

def test_fmt_num_formats_ints_and_floats():
    assert _fmt_num(7) == "7"
    assert _fmt_num(13390.5) == "13,390.50"
    assert _fmt_num(1400.0) == "1,400"
    assert _fmt_num(71.47) == "71.47"


def test_result_label_describes_filtered_agg_in_prose():
    label = _result_label({
        "target": "categorical_filtered_agg",
        "args": {"agg": "count", "value_col": "sales",
                 "filter_col": "category", "filter_value": "Electronics"},
    })
    assert label == "count of sales where category = Electronics"


def test_render_result_skips_errored_entries():
    assert _render_result({"target": "x", "error": "boom"}) is None
    assert _render_result({"target": "x", "result": None}) is None


# ── Synthesized answers ─────────────────────────────────────────────────

def test_scalar_answer_has_no_mock_marker_or_step_index():
    answer = _synthesize_answer([{
        "step_id": 1, "action": "run_stats", "target": "row_count",
        "filters": {}, "args": {}, "result": 13390.5,
    }])
    assert "(mock)" not in answer
    assert "13,390.50" in answer
    # The step_id ("1") must not appear as a bare list index.
    assert not answer.startswith("Based on the data, the key result is 1,")


def test_count_answer_reports_the_exact_number():
    answer = _synthesize_answer([{
        "step_id": 1, "action": "run_stats", "target": "categorical_filtered_agg",
        "filters": {},
        "args": {"agg": "count", "value_col": "sales",
                 "filter_col": "category", "filter_value": "Electronics"},
        "result": 7,
    }])
    assert "(mock)" not in answer
    assert "count of sales where category = Electronics: 7" in answer


def test_multi_step_answer_includes_every_named_value():
    answer = _synthesize_answer([
        {"step_id": 1, "action": "run_stats", "target": "categorical_filtered_agg",
         "filters": {},
         "args": {"agg": "mean", "value_col": "sales",
                  "filter_col": "region", "filter_value": "North"},
         "result": 534.0},
        {"step_id": 2, "action": "run_stats", "target": "categorical_filtered_agg",
         "filters": {},
         "args": {"agg": "mean", "value_col": "sales",
                  "filter_col": "region", "filter_value": "South"},
         "result": 875.1},
    ])
    assert "(mock)" not in answer
    assert "North: 534" in answer
    assert "South: 875.10" in answer
    # No unrelated group may appear.
    assert "West" not in answer


def test_grouped_dict_answer_lists_labels():
    answer = _synthesize_answer([{
        "step_id": 1, "action": "run_stats", "target": "group_compare",
        "filters": {}, "args": {},
        "result": {"South": 875.1, "West": 746.0},
    }])
    assert "South: 875.10" in answer
    assert "West: 746" in answer
    assert "(mock)" not in answer


def test_no_results_degrades_honestly():
    answer = _synthesize_answer([{"step_id": 1, "target": "x", "error": "boom"}])
    assert "(mock)" not in answer
    assert "No numeric result" in answer


# ── End-to-end through the governed path ────────────────────────────────

@pytest.fixture
def ds():
    d = DataSource(name="sample_sales_data")
    d.load_dataframe(pd.read_csv(io.StringIO(SALES_CSV)))
    return d


def test_governed_answer_has_no_internal_markers(ds):
    res = run_governed_ask(
        "How many orders are in the Electronics category?",
        ds, MockTrustProvider(), tenant_id="t_mock",
    )
    answer = res["answer"]
    assert res["results"][0]["result"] == 2
    assert "(mock)" not in answer
    assert "step_id" not in answer
    assert "2" in answer