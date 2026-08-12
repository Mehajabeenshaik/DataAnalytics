"""Tests for benchmarks/latency.py — Phase 0 latency benchmark harness.

Covers:
  - _percentile: empty list, single value, known p50/p95
  - run_benchmark: answerable question -> all four phases get one timing entry
  - run_benchmark: declined question -> execute/synthesize stay empty
  - run_benchmark: exception in one question never crashes the whole run
"""
import json
from unittest.mock import MagicMock

import pytest

from benchmarks.latency import _percentile, run_benchmark
from agent_phase2 import Plan, PlanStep
from eval.run_eval import _make_eval_ds


# ── _percentile edge cases ────────────────────────────────────────────────

class TestPercentile:
    def test_empty_list_returns_zero(self):
        assert _percentile([], 50) == 0.0
        assert _percentile([], 95) == 0.0

    def test_single_value_returns_that_value(self):
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 95) == 42.0

    def test_known_p50(self):
        # [1, 2, 3, 4, 5] -> p50 = 3
        assert _percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_known_p95(self):
        # [1, 2, 3, 4, 5] -> p95 = 4.8 (linear interpolation)
        # k = (5-1) * 0.95 = 3.8, f=3, c=4
        # s[3] + (s[4] - s[3]) * 0.8 = 4 + (5-4)*0.8 = 4.8
        assert _percentile([1, 2, 3, 4, 5], 95) == 4.8

    def test_unsorted_input(self):
        # Input order must not matter
        assert _percentile([5, 1, 3, 2, 4], 50) == 3.0


# ── run_benchmark helpers ─────────────────────────────────────────────────

def _make_answerable_provider():
    """Provider that always returns an answerable plan + valid synthesis.

    run_benchmark calls agent_phase2.plan() and agent_phase2.synthesize(),
    which both call provider.generate() — so the mock must return JSON
    strings via generate(), not expose plan()/synthesize() methods.
    """
    provider = MagicMock()
    provider.provider_name.return_value = "mock-answerable"

    def fake_generate(prompt, system_prompt="", temperature=0.1):
        if "plan" in system_prompt.lower() or "planning" in system_prompt.lower():
            # Planner response: pick the first metric from the catalog
            return json.dumps({
                "can_answer": True,
                "reason": "mock",
                "plan_type": "single_metric",
                "steps": [{"step_id": 1, "action": "run_metric", "target": "total_revenue", "filters": {}, "args": {}}],
            })
        # Synthesizer response
        return json.dumps({
            "answer": "mock answer",
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": [], "filters_applied": {}, "notes": ""},
        })

    provider.generate.side_effect = fake_generate
    return provider


def _make_declining_provider():
    """Provider that always returns a declined (no_match) plan."""
    provider = MagicMock()
    provider.provider_name.return_value = "mock-declining"

    def fake_generate(prompt, system_prompt="", temperature=0.1):
        return json.dumps({
            "can_answer": False,
            "reason": "no match",
            "plan_type": "no_match",
            "steps": [],
        })

    provider.generate.side_effect = fake_generate
    return provider


def _make_flaky_provider():
    """Provider that raises on the first question, then succeeds."""
    provider = MagicMock()
    provider.provider_name.return_value = "mock-flaky"
    state = {"calls": 0}

    def fake_generate(prompt, system_prompt="", temperature=0.1):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("simulated LLM outage")
        if "plan" in system_prompt.lower() or "planning" in system_prompt.lower():
            return json.dumps({
                "can_answer": True,
                "reason": "mock",
                "plan_type": "single_metric",
                "steps": [{"step_id": 1, "action": "run_metric", "target": "total_revenue", "filters": {}, "args": {}}],
            })
        return json.dumps({
            "answer": "mock answer",
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": [], "filters_applied": {}, "notes": ""},
        })

    provider.generate.side_effect = fake_generate
    return provider


# ── run_benchmark tests ───────────────────────────────────────────────────

class TestRunBenchmark:
    def test_answerable_question_all_four_phases_timed(self):
        """An answerable question must produce exactly one timing entry in
        every phase (plan, execute, synthesize, total)."""
        provider = _make_answerable_provider()
        ds = _make_eval_ds()

        timings, errors, provider_name, n_questions = run_benchmark(n=1, provider=provider, ds=ds)

        assert errors == 0
        assert provider_name == "mock-answerable"
        assert n_questions == 1
        assert len(timings["plan"]) == 1
        assert len(timings["execute"]) == 1
        assert len(timings["synthesize"]) == 1
        assert len(timings["total"]) == 1
        # All timings must be non-negative
        for phase in ("plan", "execute", "synthesize", "total"):
            assert timings[phase][0] >= 0

    def test_declined_question_execute_synthesize_stay_empty(self):
        """A declined question (can_answer=False) must NOT get zero entries in
        execute/synthesize — those phases stay empty so their means aren't
        dragged down by fake zeros."""
        provider = _make_declining_provider()
        ds = _make_eval_ds()

        timings, errors, provider_name, n_questions = run_benchmark(n=1, provider=provider, ds=ds)

        assert errors == 0
        assert n_questions == 1
        assert len(timings["plan"]) == 1
        assert len(timings["execute"]) == 0, "declined question must not time execute"
        assert len(timings["synthesize"]) == 0, "declined question must not time synthesize"
        assert len(timings["total"]) == 1

    def test_exception_in_one_question_does_not_crash_run(self):
        """An exception in one question must be caught, counted, and the run
        must continue with the remaining questions."""
        provider = _make_flaky_provider()
        ds = _make_eval_ds()

        timings, errors, provider_name, n_questions = run_benchmark(n=2, provider=provider, ds=ds)

        assert errors == 1, "first question should have errored"
        assert n_questions == 2
        # Second question succeeded -> all four phases have one entry
        assert len(timings["plan"]) == 1
        assert len(timings["execute"]) == 1
        assert len(timings["synthesize"]) == 1
        assert len(timings["total"]) == 1

    def test_n_limits_question_count(self):
        """--n must limit the number of questions processed."""
        provider = _make_answerable_provider()
        ds = _make_eval_ds()

        timings, errors, provider_name, n_questions = run_benchmark(n=3, provider=provider, ds=ds)

        assert n_questions == 3
        assert len(timings["plan"]) == 3
        assert len(timings["execute"]) == 3
        assert len(timings["synthesize"]) == 3
        assert len(timings["total"]) == 3