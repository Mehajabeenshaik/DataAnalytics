"""Tests for Phase 2 agent — agent_phase2.py.

Tests cover:
  - Planner: happy path, no_match, hallucinated metric/tool rejection, filter stripping
  - Propose-metric: valid proposal, invalid column, invalid agg
  - Execute: metric step, stats step, error handling
  - Synthesize: happy path, small result downgrade, malformed response
  - ask: end-to-end happy path, no_match, propose_metric flow
"""

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_source import DataSource
from agent_phase2 import (
    plan,
    propose_metric,
    execute_plan,
    synthesize,
    ask,
    Plan,
    PlanStep,
    MetricProposal,
)


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5, 6],
            "customer_id": [10, 10, 20, 30, 30, 40],
            "revenue": [100.0, 200.0, 300.0, 150.0, 250.0, 400.0],
            "quantity": [1, 2, 3, 1, 2, 4],
            "region": ["North", "South", "North", "East", "West", "South"],
            "category": ["A", "B", "A", "C", "B", "A"],
            "order_date": pd.to_datetime(
                ["2024-01-15", "2024-02-20", "2024-03-10", "2024-04-05", "2024-05-12", "2024-06-18"]
            ),
        }
    )


@pytest.fixture
def ds(sample_df):
    ds = DataSource()
    ds.load_dataframe(sample_df)
    return ds


def make_mock_provider(response_json: dict):
    provider = MagicMock()
    provider.generate.return_value = json.dumps(response_json)
    return provider


# ── Planner tests ─────────────────────────────────────────────────────────

def test_plan_single_metric(ds):
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Metric exists",
        "plan_type": "single_metric",
        "steps": [
            {"step_id": 1, "action": "run_metric", "target": first_metric, "filters": {}, "args": {}}
        ],
    })
    the_plan = plan("What is total revenue?", ds, provider)
    assert the_plan.can_answer is True
    assert the_plan.plan_type == "single_metric"
    assert len(the_plan.steps) == 1
    assert the_plan.steps[0].target == first_metric


def test_plan_stats_tool(ds):
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Need stats",
        "plan_type": "stats_tool",
        "steps": [
            {"step_id": 1, "action": "run_stats", "target": "describe", "filters": {}, "args": {"columns": ["revenue"]}}
        ],
    })
    the_plan = plan("Describe the data", ds, provider)
    assert the_plan.can_answer is True
    assert the_plan.plan_type == "stats_tool"
    assert the_plan.steps[0].target == "describe"


def test_plan_no_match(ds):
    provider = make_mock_provider({
        "can_answer": False,
        "reason": "No relevant metric or tool",
        "plan_type": "no_match",
        "steps": [],
    })
    the_plan = plan("What's the weather?", ds, provider)
    assert the_plan.can_answer is False
    assert the_plan.plan_type == "no_match"


def test_plan_hallucinated_metric_rejected(ds):
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Found metric",
        "plan_type": "single_metric",
        "steps": [
            {"step_id": 1, "action": "run_metric", "target": "fake_metric", "filters": {}, "args": {}}
        ],
    })
    the_plan = plan("What is CLV?", ds, provider)
    assert the_plan.can_answer is False
    assert the_plan.plan_type == "no_match"


def test_plan_hallucinated_tool_rejected(ds):
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Found tool",
        "plan_type": "stats_tool",
        "steps": [
            {"step_id": 1, "action": "run_stats", "target": "hack_database", "filters": {}, "args": {}}
        ],
    })
    the_plan = plan("Hack the database", ds, provider)
    assert the_plan.can_answer is False
    assert the_plan.plan_type == "no_match"


def test_plan_strips_non_allowlisted_filters(ds):
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Found metric",
        "plan_type": "single_metric",
        "steps": [
            {
                "step_id": 1,
                "action": "run_metric",
                "target": first_metric,
                "filters": {"region": "North", "malicious_col": "drop table"},
                "args": {},
            }
        ],
    })
    the_plan = plan("revenue in North", ds, provider)
    assert "malicious_col" not in the_plan.steps[0].filters
    assert "region" in the_plan.steps[0].filters


def test_plan_malformed_json(ds):
    provider = MagicMock()
    provider.generate.return_value = "not valid json"
    the_plan = plan("revenue?", ds, provider)
    assert the_plan.can_answer is False
    assert the_plan.plan_type == "no_match"


def test_plan_caps_steps_at_three(ds):
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Multi-step",
        "plan_type": "multi_step",
        "steps": [
            {"step_id": i, "action": "run_metric", "target": first_metric, "filters": {}, "args": {}}
            for i in range(1, 6)
        ],
    })
    the_plan = plan("complex question", ds, provider)
    assert len(the_plan.steps) <= 3


# ── Propose-metric tests ──────────────────────────────────────────────────

def test_propose_metric_valid(ds):
    provider = make_mock_provider({
        "can_propose": True,
        "proposed_name": "median_revenue",
        "synonyms": ["median revenue", "middle revenue"],
        "description": "Median of revenue across all rows.",
        "column": "revenue",
        "agg": "mean",
        "groupby": None,
        "base_filters": {},
        "why_needed": "User asked for median",
        "risk": "low",
    })
    proposal = propose_metric("What is the median revenue?", ds, provider)
    assert proposal.can_propose is True
    assert proposal.column == "revenue"
    assert proposal.agg == "mean"


def test_propose_metric_invalid_column(ds):
    provider = make_mock_provider({
        "can_propose": True,
        "proposed_name": "bad_metric",
        "synonyms": ["bad"],
        "description": "Bad metric.",
        "column": "nonexistent_col",
        "agg": "sum",
        "groupby": None,
        "base_filters": {},
        "why_needed": "test",
        "risk": "low",
    })
    proposal = propose_metric("bad question", ds, provider)
    assert proposal.can_propose is False


def test_propose_metric_invalid_agg(ds):
    provider = make_mock_provider({
        "can_propose": True,
        "proposed_name": "bad_agg",
        "synonyms": ["bad"],
        "description": "Bad agg.",
        "column": "revenue",
        "agg": "median",
        "groupby": None,
        "base_filters": {},
        "why_needed": "test",
        "risk": "low",
    })
    proposal = propose_metric("bad question", ds, provider)
    assert proposal.can_propose is False


def test_propose_metric_malformed_json(ds):
    provider = MagicMock()
    provider.generate.return_value = "garbage"
    proposal = propose_metric("question", ds, provider)
    assert proposal.can_propose is False


# ── Execute tests ─────────────────────────────────────────────────────────

def test_execute_plan_metric_step(ds):
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    the_plan = Plan(
        can_answer=True,
        reason="test",
        plan_type="single_metric",
        steps=[PlanStep(step_id=1, action="run_metric", target=first_metric)],
    )
    results = execute_plan(the_plan, ds)
    assert len(results) == 1
    assert results[0]["error"] is None
    assert results[0]["result"] is not None


def test_execute_plan_stats_step(ds):
    the_plan = Plan(
        can_answer=True,
        reason="test",
        plan_type="stats_tool",
        steps=[PlanStep(step_id=1, action="run_stats", target="describe", args={"columns": ["revenue"]})],
    )
    results = execute_plan(the_plan, ds)
    assert len(results) == 1
    assert results[0]["error"] is None
    assert isinstance(results[0]["result"], pd.DataFrame)


def test_execute_plan_error_handling(ds):
    the_plan = Plan(
        can_answer=True,
        reason="test",
        plan_type="stats_tool",
        steps=[PlanStep(step_id=1, action="run_stats", target="describe", args={"columns": ["nonexistent_col"]})],
    )
    results = execute_plan(the_plan, ds)
    assert len(results) == 1
    assert results[0]["error"] is not None


# ── Synthesize tests ──────────────────────────────────────────────────────

def test_synthesize_happy_path(ds):
    provider = make_mock_provider({
        "answer": "Total revenue is 1400.",
        "confidence": "high",
        "caveats": [],
        "lineage": {"metrics_or_tools_used": ["total_revenue"], "filters_applied": {}, "notes": "6 rows"},
    })
    the_plan = Plan(can_answer=True, reason="test", plan_type="single_metric")
    results = [{"step_id": 1, "action": "run_metric", "target": "total_revenue", "filters": {}, "args": {}, "result": 1400.0, "error": None}]
    answer = synthesize("What is total revenue?", the_plan, results, provider)
    assert answer["confidence"] == "high"
    assert "1400" in answer["answer"]


def test_synthesize_downgrades_small_result(ds):
    provider = make_mock_provider({
        "answer": "Breakdown shown.",
        "confidence": "high",
        "caveats": [],
        "lineage": {"metrics_or_tools_used": ["revenue_by_region"], "filters_applied": {}, "notes": "2 rows"},
    })
    the_plan = Plan(can_answer=True, reason="test", plan_type="single_metric")
    small_series = pd.Series([100, 200], index=["A", "B"])
    results = [{"step_id": 1, "action": "run_metric", "target": "revenue_by_region", "filters": {}, "args": {}, "result": small_series, "error": None}]
    answer = synthesize("breakdown", the_plan, results, provider)
    assert answer["confidence"] == "low"
    assert any("Small result set" in c for c in answer.get("caveats", []))


def test_synthesize_malformed_response(ds):
    provider = MagicMock()
    provider.generate.return_value = "garbage"
    the_plan = Plan(can_answer=True, reason="test", plan_type="single_metric")
    results = [{"step_id": 1, "action": "run_metric", "target": "total_revenue", "filters": {}, "args": {}, "result": 1400.0, "error": None}]
    answer = synthesize("question", the_plan, results, provider)
    assert answer["confidence"] == "low"


# ── ask end-to-end tests ───────────────────────────────────────────

def test_ask_happy_path(ds):
    metrics = ds.get_metrics()
    first_metric = list(metrics.keys())[0]
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({
            "can_answer": True,
            "reason": "Found metric",
            "plan_type": "single_metric",
            "steps": [
                {"step_id": 1, "action": "run_metric", "target": first_metric, "filters": {}, "args": {}}
            ],
        }),
        json.dumps({
            "answer": "Result computed.",
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": [first_metric], "filters_applied": {}, "notes": "6 rows"},
        }),
    ]
    result = ask("What is the total?", ds, provider)
    assert result["plan"]["plan_type"] == "single_metric"
    assert len(result["results"]) == 1
    assert result["results"][0]["error"] is None
    assert result["confidence"] in ("high", "low")


def test_ask_no_match(ds):
    provider = make_mock_provider({
        "can_answer": False,
        "reason": "No match",
        "plan_type": "no_match",
        "steps": [],
    })
    result = ask("What's the weather?", ds, provider)
    assert result["plan"]["plan_type"] == "no_match"
    assert result["results"] == []
    assert "don't have a reliable" in result["answer"]


def test_ask_propose_metric(ds):
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({
            "can_answer": True,
            "reason": "Needs new metric",
            "plan_type": "propose_metric",
            "steps": [],
        }),
        json.dumps({
            "can_propose": True,
            "proposed_name": "median_revenue",
            "synonyms": ["median revenue"],
            "description": "Median of revenue.",
            "column": "revenue",
            "agg": "mean",
            "groupby": None,
            "base_filters": {},
            "why_needed": "User asked for median",
            "risk": "low",
        }),
    ]
    result = ask("What is the median revenue?", ds, provider)
    assert result["plan"]["plan_type"] == "propose_metric"
    assert "proposal" in result
    assert result["proposal"]["can_propose"] is True
    assert result["proposal"]["column"] == "revenue"


def test_ask_stats_tool(ds):
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({
            "can_answer": True,
            "reason": "Use describe tool",
            "plan_type": "stats_tool",
            "steps": [
                {"step_id": 1, "action": "run_stats", "target": "describe", "filters": {}, "args": {"columns": ["revenue"]}}
            ],
        }),
        json.dumps({
            "answer": "Summary stats computed.",
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": ["describe"], "filters_applied": {}, "notes": "6 rows"},
        }),
    ]
    result = ask("Describe the revenue column", ds, provider)
    assert result["plan"]["plan_type"] == "stats_tool"
    assert len(result["results"]) == 1
    assert result["results"][0]["target"] == "describe"
    assert result["results"][0]["error"] is None