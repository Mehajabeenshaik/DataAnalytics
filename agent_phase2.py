"""
Phase 2 governed agent — planner → execute → synthesizer loop.

Extends Phase 1 with:
  - A planner that can route to single_metric, stats_tool, multi_step, or propose_metric
  - 6 deterministic statistical tools (stats_tools.py)
  - A propose-metric flow (human approval required)
  - A synthesizer that produces grounded answers with confidence + lineage

Safety model is fully preserved:
  - LLM only picks from the metric catalog and allowed tool names
  - Filters are stripped against the allowlist
  - All column validation happens in the deterministic layer
  - No raw SQL or Python from the LLM is ever executed
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from pydantic import BaseModel, ValidationError

from data_source import DataSource
from metric_factory import get_metric_catalog_for_llm
from agent_core import run_metric
from stats_tools import ALLOWED_STATS_TOOLS, VALID_TOOL_NAMES, run_stats_tool
from llm_provider import LLMProvider


# ── Prompts ───────────────────────────────────────────────────────────────

PLANNER_SYSTEM = """You are the planning module of a local data analyst agent (Nemotron).

Given:
- The user question
- The current metric catalog (name, synonyms, description only)
- The list of allowed statistical tools
- The schema card (column names + types + examples)
- Allowed filter columns

Produce a plan in STRICT JSON only:

{
  "can_answer": true | false,
  "reason": "short explanation",
  "plan_type": "single_metric" | "stats_tool" | "multi_step" | "propose_metric" | "no_match",
  "steps": [
    {
      "step_id": 1,
      "action": "run_metric" | "run_stats",
      "target": "<metric_name or tool_name>",
      "filters": {"column": "value"},
      "args": {}
    }
  ]
}

Rules:
- Maximum 3 steps.
- Only use metric names that appear in the catalog.
- Only use tool names from the allowed tools list.
- Filters may only use columns from the allowed filter list.
- If the question needs a calculation that does not exist yet, use plan_type = "propose_metric".
- If nothing is appropriate, set can_answer = false and plan_type = "no_match".
- Output ONLY valid JSON. No markdown, no extra text.
"""

PROPOSE_METRIC_SYSTEM = """You are proposing a new governed metric for a local data analyst system.

The user asked a question that cannot be answered by the current metric catalog.
Propose ONE new metric that would answer it, using only columns that exist in the schema.

Output STRICT JSON only:
{
  "can_propose": true,
  "proposed_name": "snake_case_name",
  "synonyms": ["...", "..."],
  "description": "One clear sentence describing what this metric measures",
  "column": "<existing column name>",
  "agg": "sum" | "mean" | "count" | "nunique",
  "groupby": "<column or null>",
  "base_filters": {},
  "why_needed": "Short reason this metric is required",
  "risk": "low" | "medium" | "high"
}

Rules:
- column and groupby must already exist in the schema.
- agg must be one of: sum, mean, count, nunique.
- Never invent columns or complex expressions.
- If you cannot propose a safe metric, return:
  {"can_propose": false, "reason": "..."}
- Output ONLY valid JSON.
"""

SYNTHESIZER_SYSTEM = """You are a senior data analyst writing the final answer for a business user.
You are running on Nemotron and must stay strictly grounded in the data.

You receive:
- The original question
- The plan that was executed
- The exact results returned by the tools/metrics

Write a response in STRICT JSON only:
{
  "answer": "Clear, concise plain-English answer. Use only numbers that appear in the results.",
  "confidence": "high" | "low",
  "caveats": ["list of important limitations or assumptions"],
  "lineage": {
    "metrics_or_tools_used": ["..."],
    "filters_applied": {},
    "notes": "row counts or sample size notes if relevant"
  }
}

Rules:
- Never invent or round numbers beyond what the tools returned.
- If the result set is small, confidence must be "low".
- If the question implies causation and the data only shows association, say so in caveats.
- Keep the answer short and decision-oriented.
- Output ONLY valid JSON.
"""


# ── Pydantic models ───────────────────────────────────────────────────────

class PlanStep(BaseModel):
    step_id: int = 1
    action: str = "run_metric"  # "run_metric" | "run_stats"
    target: str = ""
    filters: dict = {}
    args: dict = {}


class Plan(BaseModel):
    can_answer: bool = False
    reason: str = ""
    plan_type: str = "no_match"  # single_metric | stats_tool | multi_step | propose_metric | no_match
    steps: list[PlanStep] = []


class MetricProposal(BaseModel):
    can_propose: bool = False
    proposed_name: str = ""
    synonyms: list[str] = []
    description: str = ""
    column: str = ""
    agg: str = "sum"
    groupby: str | None = None
    base_filters: dict = {}
    why_needed: str = ""
    risk: str = "low"


# ── Step 1: Planner (LLM call #1) ─────────────────────────────────────────

def plan(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
) -> Plan:
    """Ask the LLM to produce a plan for answering the question.

    The LLM sees only:
      - Metric names + synonyms + descriptions (no SQL logic)
      - Stats tool names + descriptions (no implementation)
      - Schema card (column names + types + examples)
      - Allowed filter column names

    The returned Plan is validated: metric names must exist in the catalog,
    tool names must be in the allowed set, and filter keys are stripped
    against the allowlist.
    """
    metrics = ds.get_metrics()
    catalog = get_metric_catalog_for_llm(metrics)
    schema_card = ds.get_schema_card()
    allowed_filters = ds.allowed_filter_columns

    # Build the tools catalog for the prompt
    tools_catalog = [
        {"name": t["name"], "description": t["description"], "args": t["args"]}
        for t in ALLOWED_STATS_TOOLS
    ]

    prompt = (
        f"Schema:\n{schema_card}\n\n"
        f"Allowed filter columns: {allowed_filters}\n\n"
        f"Available metrics:\n{json.dumps(catalog, indent=2)}\n\n"
        f"Available statistical tools:\n{json.dumps(tools_catalog, indent=2)}\n\n"
        f"Question: {question}"
    )

    raw = provider.generate(prompt, system_prompt=PLANNER_SYSTEM, temperature=0.05)

    try:
        data = json.loads(raw)
        the_plan = Plan(**data)
    except (json.JSONDecodeError, ValidationError):
        return Plan(can_answer=False, reason="Malformed planner response", plan_type="no_match")

    # ── Safety: validate every step ──────────────────────────────────
    metric_names = set(metrics.keys())
    for step in the_plan.steps:
        # Validate action
        if step.action not in ("run_metric", "run_stats"):
            step.action = "run_metric"  # safe default

        # Validate target
        if step.action == "run_metric" and step.target not in metric_names:
            # LLM invented a metric name — reject the whole plan
            return Plan(
                can_answer=False,
                reason=f"Metric '{step.target}' not in catalog",
                plan_type="no_match",
            )
        if step.action == "run_stats" and step.target not in VALID_TOOL_NAMES:
            return Plan(
                can_answer=False,
                reason=f"Tool '{step.target}' not in allowed tools",
                plan_type="no_match",
            )

        # Strip non-allowlisted filter keys
        step.filters = {
            k: v for k, v in step.filters.items() if k in allowed_filters
        }

    # Cap steps at 3
    the_plan.steps = the_plan.steps[:3]

    return the_plan


# ── Step 2: Propose-metric (LLM call, only if plan_type == propose_metric) ──

def propose_metric(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
) -> MetricProposal:
    """Ask the LLM to propose a new governed metric.

    The proposal is validated: column must exist, agg must be valid.
    The proposal does NOT enter the live catalog until a human approves it.
    """
    schema_card = ds.get_schema_card()
    column_names = [c.name for c in ds.profile.columns]

    prompt = (
        f"Schema:\n{schema_card}\n\n"
        f"Available columns: {column_names}\n\n"
        f"Question that needs a new metric: {question}"
    )

    raw = provider.generate(prompt, system_prompt=PROPOSE_METRIC_SYSTEM, temperature=0.2)

    try:
        data = json.loads(raw)
        proposal = MetricProposal(**data)
    except (json.JSONDecodeError, ValidationError):
        return MetricProposal(can_propose=False, reason="Malformed proposal response")

    # Validate column exists
    if proposal.can_propose:
        if proposal.column not in column_names:
            return MetricProposal(
                can_propose=False,
                reason=f"Proposed column '{proposal.column}' does not exist",
            )
        if proposal.agg not in ("sum", "mean", "count", "nunique"):
            return MetricProposal(
                can_propose=False,
                reason=f"Invalid agg '{proposal.agg}'",
            )
        if proposal.groupby and proposal.groupby not in column_names:
            return MetricProposal(
                can_propose=False,
                reason=f"Proposed groupby '{proposal.groupby}' does not exist",
            )

    return proposal


# ── Step 3: Execute (deterministic, no LLM) ──────────────────────────────

def execute_plan(the_plan: Plan, ds: DataSource) -> list[dict]:
    """Execute each step in the plan deterministically.

    Returns a list of result dicts, one per step:
      [{"step_id": 1, "action": "run_metric", "target": "...", "result": <data>}]
    """
    results: list[dict] = []
    metrics = ds.get_metrics()

    for step in the_plan.steps:
        result_entry: dict[str, Any] = {
            "step_id": step.step_id,
            "action": step.action,
            "target": step.target,
            "filters": step.filters,
            "args": step.args,
            "result": None,
            "error": None,
        }

        try:
            if step.action == "run_metric":
                metric = metrics[step.target]
                result = run_metric(ds, metric, step.filters)
                result_entry["result"] = result
            elif step.action == "run_stats":
                result = run_stats_tool(ds, step.target, step.args)
                result_entry["result"] = result
        except Exception as e:
            result_entry["error"] = str(e)

        results.append(result_entry)

    return results


# ── Step 4: Synthesize (LLM call #2) ──────────────────────────────────────

def synthesize(
    question: str,
    the_plan: Plan,
    results: list[dict],
    provider: LLMProvider,
) -> dict:
    """Ask the LLM to write the final answer grounded in the tool results.

    The LLM receives the question, the plan, and the raw results.
    It must not invent numbers — only use what the tools returned.
    """
    # Serialize results for the prompt (handle DataFrames, Series, etc.)
    serializable_results = []
    for r in results:
        entry = {
            "step_id": r["step_id"],
            "action": r["action"],
            "target": r["target"],
            "filters": r["filters"],
            "args": r["args"],
        }
        if r.get("error"):
            entry["error"] = r["error"]
        else:
            val = r["result"]
            if isinstance(val, pd.DataFrame):
                entry["result"] = val.to_dict(orient="records")
            elif isinstance(val, pd.Series):
                entry["result"] = val.to_dict()
            elif isinstance(val, (int, float)):
                entry["result"] = val
            else:
                entry["result"] = str(val)
        serializable_results.append(entry)

    prompt = (
        f"Question: {question}\n\n"
        f"Plan: {the_plan.model_dump_json()}\n\n"
        f"Results:\n{json.dumps(serializable_results, indent=2, default=str)}"
    )

    raw = provider.generate(prompt, system_prompt=SYNTHESIZER_SYSTEM, temperature=0.3)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "answer": str(serializable_results),
            "confidence": "low",
            "caveats": ["Could not generate a clean explanation."],
            "lineage": {
                "metrics_or_tools_used": [r["target"] for r in results],
                "filters_applied": {},
                "notes": "Fallback — raw results shown.",
            },
        }

    # Safety: downgrade confidence for small result sets
    for r in results:
        val = r.get("result")
        if hasattr(val, "__len__") and not isinstance(val, (str, dict)) and len(val) < 3:
            if data.get("confidence") == "high":
                data["confidence"] = "low"
                caveats = data.get("caveats", [])
                caveats.append("Small result set — interpret with caution.")
                data["caveats"] = caveats

    return data


# ── Top-level entrypoint ─────────────────────────────────────────────────

def ask_phase2(question: str, ds: DataSource, provider: LLMProvider) -> dict:
    """Phase 2 agent loop: plan → execute → synthesize.

    Returns a dict with:
      - answer: plain-English explanation
      - confidence: "high" | "low"
      - caveats: list of strings
      - lineage: dict with tools/filters used
      - plan: the plan that was executed
      - results: raw step results
      - proposal: (only if plan_type == "propose_metric") the metric proposal

    If the plan is no_match, returns an honest decline.
    If the plan is propose_metric, returns the proposal for human approval.
    """
    # Step 1: Plan
    the_plan = plan(question, ds, provider)

    if not the_plan.can_answer or the_plan.plan_type == "no_match":
        return {
            "answer": "I don't have a reliable metric or tool that answers this question with the current data.",
            "confidence": "n/a",
            "caveats": ["No matching metric or tool in the allowlist."],
            "lineage": {"metrics_or_tools_used": [], "filters_applied": {}, "notes": "no_match"},
            "plan": the_plan.model_dump(),
            "results": [],
        }

    # If propose_metric, generate a proposal (does not execute anything)
    if the_plan.plan_type == "propose_metric":
        proposal = propose_metric(question, ds, provider)
        return {
            "answer": "This question needs a new metric. I've drafted a proposal for your review.",
            "confidence": "n/a",
            "caveats": ["Proposed metric requires human approval before use."],
            "lineage": {
                "metrics_or_tools_used": [],
                "filters_applied": {},
                "notes": "propose_metric flow",
            },
            "plan": the_plan.model_dump(),
            "results": [],
            "proposal": proposal.model_dump(),
        }

    # Step 2: Execute
    results = execute_plan(the_plan, ds)

    # Step 3: Synthesize
    answer = synthesize(question, the_plan, results, provider)

    return {
        **answer,
        "plan": the_plan.model_dump(),
        "results": results,
    }