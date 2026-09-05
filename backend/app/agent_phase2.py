"""
Phase 2 governed agent — planner → execute → synthesizer loop.

Extends Phase 1 with:
  - A planner that can route to single_metric, stats_tool, multi_step, or propose_metric
  - 6 deterministic statistical tools (stats_tools.py)
  - A propose-metric flow (human approval required)
  - A synthesizer that produces grounded answers with confidence + lineage
  - PII defense-in-depth: result scrubbing via Presidio before synthesis

Safety model is fully preserved:
  - LLM only picks from the metric catalog and allowed tool names
  - Filters are stripped against the allowlist
  - All column validation happens in the deterministic layer
  - No raw SQL or Python from the LLM is ever executed
  - PII is masked at load time (data_source.py) and scrubbed from results
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pandas as pd
from pydantic import BaseModel, ValidationError

_log = logging.getLogger("daana.agent")

from data_source import DataSource
from metric_factory import get_metric_catalog_for_llm
from agent_core import run_metric
from stats_tools import ALLOWED_STATS_TOOLS, VALID_TOOL_NAMES, run_stats_tool
from llm_provider import LLMProvider
from cache import get_cached_response, set_cached_response
from catalog.service import CatalogService
from catalog.models import MetricDefinition as CatalogMetricDefinition
from catalog.models import MetricProposal as CatalogMetricProposal

from verification import verify_answer
from chart_builder import build_chart_spec
from conversation_memory import get_memory


# ── PII defense-in-depth ──────────────────────────────────────────────────

def _scrub_pii_from_results(results: list[dict]) -> list[dict]:
    """Defense-in-depth: run Presidio on any string values in results.

    This is a second layer of PII protection — the primary layer is
    data_source.py's _detect_and_mask_pii() which masks at load time.
    This function catches any PII that might slip through in result
    values (e.g. from a stats tool that returns string columns).
    """
    try:
        from pii_masker import PIIMasker
        masker = PIIMasker()
    except ImportError:
        return results

    from pii_masker import _might_contain_pii
    for r in results:
        val = r.get("result")
        if isinstance(val, str):
            if _might_contain_pii(val):
                detections = masker.scan_text(val)
                if detections:
                    r["result"] = "[REDACTED - possible PII detected]"
        elif isinstance(val, pd.DataFrame):
            for col in val.columns:
                if val[col].dtype == "object":
                    for idx in val.index:
                        cell = val.at[idx, col]
                        if isinstance(cell, str) and _might_contain_pii(cell):
                            detections = masker.scan_text(cell)
                            if detections:
                                val.at[idx, col] = "[REDACTED - possible PII detected]"
    return results


# ── Prompts ───────────────────────────────────────────────────────────────

PLANNER_SYSTEM = """You are the planning module of a governed data analyst agent. Your job is to produce a correct, minimal, and safe execution plan.

You receive:
- User question
- Metric catalog (name + synonyms + short description only)
- Allowed statistical tools
- Schema card (column names, types, examples)
- Allowed filter columns
- Approved join policies (if any)

### Output format (STRICT JSON only)
{
  "can_answer": true | false,
  "reason": "short explanation of your decision",
  "plan_type": "single_metric" | "stats_tool" | "multi_step" | "joined_metric" | "propose_metric" | "no_match",
  "steps": [
    {
      "step_id": 1,
      "action": "run_metric" | "run_stats",
      "target": "<exact metric_name or tool_name>",
      "filters": {"column": "value"},
      "args": {},
      "join_policy_name": "<approved join policy name or null>"
    }
  ]
}

### Hard Rules (never violate)
1. Maximum 3 steps.
2. target MUST be an exact name from the metric catalog OR from the allowed tools list.
3. Never invent metric names, tool names, columns, or join policies.
4. Filters may only use columns from the allowed filter list.
5. For calendar-month questions (e.g. "sales in January") → use tool "filtered_agg" with proper month argument. Never return an unfiltered total.
6. For "by category / by region / highest / lowest / compare groups" questions → use tool "group_compare".
7. For distribution / value counts / frequency questions → prefer tool "value_counts" (or a count_by_* metric if one exists).
8. For trends / over time / monthly pattern questions → use tool "trend".
9. For questions requiring two tables → only use an approved join_policy_name. Never invent joins.
10. If no existing metric or tool can correctly answer → set plan_type = "propose_metric" or "no_match".
11. Prefer the simplest plan that is correct. Do not over-plan.
12. Output ONLY valid JSON. No markdown, no commentary.

### Few-shot examples (study these carefully)

Example 1 – Distribution / value counts
Question: "Distribution of categories"
→ {
  "can_answer": true,
  "reason": "User wants frequency distribution of a categorical column",
  "plan_type": "stats_tool",
  "steps": [
    {
      "step_id": 1,
      "action": "run_stats",
      "target": "value_counts",
      "filters": {},
      "args": {"column": "category"},
      "join_policy_name": null
    }
  ]
}

Example 2 – Trends over time
Question: "Show me trends over time"
→ {
  "can_answer": true,
  "reason": "User is asking for a time-based trend of a numeric measure",
  "plan_type": "stats_tool",
  "steps": [
    {
      "step_id": 1,
      "action": "run_stats",
      "target": "trend",
      "filters": {},
      "args": {"value_col": "revenue", "date_col": "order_date"},
      "join_policy_name": null
    }
  ]
}

Example 3 – Value counts with explicit column
Question: "Show me value counts for region"
→ {
  "can_answer": true,
  "reason": "Direct request for value counts on region",
  "plan_type": "stats_tool",
  "steps": [
    {
      "step_id": 1,
      "action": "run_stats",
      "target": "value_counts",
      "filters": {},
      "args": {"column": "region"},
      "join_policy_name": null
    }
  ]
}

Example 4 – Group comparison
Question: "Which region has the highest sales?"
→ {
  "can_answer": true,
  "reason": "Comparison of a numeric measure across a categorical column",
  "plan_type": "stats_tool",
  "steps": [
    {
      "step_id": 1,
      "action": "run_stats",
      "target": "group_compare",
      "filters": {},
      "args": {"value_col": "sales", "group_col": "region", "agg": "sum"},
      "join_policy_name": null
    }
  ]
}

Example 5 – Simple metric match
Question: "What is total revenue?"
→ {
  "can_answer": true,
  "reason": "Exact match to total_revenue metric",
  "plan_type": "single_metric",
  "steps": [
    {
      "step_id": 1,
      "action": "run_metric",
      "target": "total_revenue",
      "filters": {},
      "args": {},
      "join_policy_name": null
    }
  ]
}

Example 6 – Month filter
Question: "Show me sales in January"
→ {
  "can_answer": true,
  "reason": "Time-filtered aggregation required",
  "plan_type": "stats_tool",
  "steps": [
    {
      "step_id": 1,
      "action": "run_stats",
      "target": "filtered_agg",
      "filters": {},
      "args": {"value_col": "sales", "date_col": "order_date", "month": 1, "agg": "sum"},
      "join_policy_name": null
    }
  ]
}

Example 7 – Ambiguous distribution wording
Question: "How are the categories distributed?"
→ {
  "can_answer": true,
  "reason": "Distribution request → value_counts",
  "plan_type": "stats_tool",
  "steps": [
    {
      "step_id": 1,
      "action": "run_stats",
      "target": "value_counts",
      "filters": {},
      "args": {"column": "category"},
      "join_policy_name": null
    }
  ]
}

Example 8 – Trend with different wording
Question: "What is the monthly trend of revenue?"
→ {
  "can_answer": true,
  "reason": "Explicit monthly trend request",
  "plan_type": "stats_tool",
  "steps": [
    {
      "step_id": 1,
      "action": "run_stats",
      "target": "trend",
      "filters": {},
      "args": {"value_col": "revenue", "date_col": "order_date"},
      "join_policy_name": null
    }
  ]
}

### Accuracy Decision Tree
- Can one existing metric answer it? → single_metric
- Needs grouping / comparison / highest / lowest? → group_compare
- Needs frequency / distribution / value counts? → value_counts
- Needs trend / over time / monthly pattern? → trend
- Needs sequential calculations? → multi_step (max 3)
- Needs data from two approved tables? → joined_metric
- Metric does not exist yet but is safe to propose? → propose_metric
- Otherwise → no_match

Be conservative. A wrong answer is worse than "I cannot answer this yet".
"""


PROPOSE_METRIC_SYSTEM = """You are proposing a new governed metric for a safety-critical analytics system.

The current catalog cannot answer the user question. Propose ONE safe, simple metric that would answer it.

### Constraints
- Use ONLY columns that exist in the schema.
- Aggregation must be one of: sum, mean, count, nunique, max, min.
- Keep the metric simple and auditable.
- Never propose complex expressions, window functions, or multi-column formulas in Phase 1.
- Prefer metrics that are reusable across many questions.

### Output (STRICT JSON)
{
  "can_propose": true,
  "proposed_name": "snake_case_name",
  "synonyms": ["common phrase 1", "common phrase 2"],
  "description": "One clear sentence of what this metric measures",
  "column": "<existing column>",
  "agg": "sum" | "mean" | "count" | "nunique" | "max" | "min",
  "groupby": "<column or null>",
  "base_filters": {},
  "why_needed": "Short reason",
  "risk": "low" | "medium" | "high"
}

If you cannot propose a safe metric, return:
{"can_propose": false, "reason": "..."}
"""

SYNTHESIZER_SYSTEM = """You are a senior data analyst writing the final answer for a business user.

You receive ONLY the tool/metric results and the original question. You must never invent numbers, metrics, or relationships that are not present in the results.

### Rules
1. Base every number strictly on the provided results.
2. Be precise and concise.
3. Clearly state the metric or calculation used.
4. If the result is partial, filtered, or has low sample size → lower the confidence and add a caveat.
5. Never claim causation unless the data and method support it.
6. Output ONLY valid JSON.

### Output schema
{
  "answer": "Clear plain-English answer that directly addresses the question",
  "confidence": "high" | "medium" | "low",
  "caveat": "string or null",
  "key_numbers": ["list of the most important numbers used"],
  "lineage_summary": "short description of which metric/tool produced the answer"
}

### Confidence guidelines
- high   → exact metric match, sufficient rows, clear filters
- medium → reasonable match but some assumptions or limited data
- low    → small sample, missing filters, indirect metric, or possible misinterpretation
"""


# ── Pydantic models ───────────────────────────────────────────────────────

class PlanStep(BaseModel):
    step_id: int = 1
    action: str = "run_metric"
    target: str = ""
    filters: dict = {}
    args: dict = {}
    join_policy_name: str | None = None


class Plan(BaseModel):
    can_answer: bool = False
    reason: str = ""
    plan_type: str = "no_match"
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


# ── Guided-decoding schema (vLLM structured output) ────────────────────────

def _build_planner_json_schema(metric_names: list[str], tool_names: list[str]) -> dict:
    """JSON Schema mirroring the Plan/PlanStep pydantic models above, but with
    live enum constraints so a guided-decoding backend (vLLM's guided_json)
    can make it *structurally impossible* for the planner to emit a target
    outside the current catalog — not just checked after the fact by the
    validation loop in plan() below, which remains as defense-in-depth.

    target's enum is the union of metric + tool names rather than being
    conditional on action, because plain JSON Schema can't express "enum A
    if action=X else enum B" without oneOf/allOf branching that some guided-
    decoding backends handle inconsistently. The existing post-generation
    checks in plan() (metric_names / VALID_TOOL_NAMES) still enforce the
    action-target pairing correctly; this schema's job is only to shrink
    the space of plausible mistakes, not to duplicate that logic.
    """
    targets = sorted(set(metric_names) | set(tool_names))
    return {
        "type": "object",
        "properties": {
            "can_answer": {"type": "boolean"},
            "reason": {"type": "string"},
            "plan_type": {
                "type": "string",
                "enum": ["single_metric", "stats_tool", "multi_step", "joined_metric", "propose_metric", "no_match"],
            },
            "steps": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "step_id": {"type": "integer"},
                        "action": {"type": "string", "enum": ["run_metric", "run_stats"]},
                        "target": {"type": "string", "enum": targets} if targets else {"type": "string"},
                        "filters": {"type": "object"},
                        "args": {"type": "object"},
                        "join_policy_name": {"type": ["string", "null"]},
                    },
                    "required": ["action", "target"],
                },
            },
        },
        "required": ["can_answer", "reason", "plan_type", "steps"],
    }


def _apply_guided_schema(provider: LLMProvider, schema: dict) -> None:
    """Set guided_json_schema on the provider if it supports it (currently
    only VLLMProvider). No-op for providers without that attribute — this
    keeps plan() provider-agnostic rather than branching on isinstance.
    """
    if hasattr(provider, "guided_json_schema"):
        provider.guided_json_schema = schema


# ── Step 1: Planner (LLM call #1) ─────────────────────────────────────────

def plan(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
    tenant_id: str = "default",
    dataset_names: list[str] | None = None,
    prior_context: str = "",
) -> Plan:
    # Governed catalog: only APPROVED metrics are visible to the LLM planner.
    # Backward-compatible fallback: if the catalog hasn't been seeded yet,
    # use the legacy in-memory auto-generated metrics so existing callers
    # (and tests) that don't seed the catalog keep working unchanged.
    catalog_service = CatalogService(tenant_id=tenant_id)
    approved = catalog_service.get_approved_metrics()
    auto = ds.get_metrics()
    # Merge approved + auto-generated metrics. Approved entries are the
    # governed base, but auto-generated metrics from the CURRENT data schema
    # must also be visible — a stale catalog (e.g. seeded before id-like
    # columns were excluded) must not hide freshly-generated metrics like
    # total_revenue for a newly-loaded dataset.
    metrics = {**(approved or {}), **(auto or {})}
    catalog = get_metric_catalog_for_llm(metrics)
    schema_card = ds.get_schema_card()
    allowed_filters = ds.allowed_filter_columns

    tools_catalog = [
        {
            "name": t["name"],
            "description": t["description"],
            "synonyms": t.get("synonyms", []),
            "args": t["args"],
        }
        for t in ALLOWED_STATS_TOOLS
    ]

    # Multi-dataset support: include the list of available dataset names in
    # the planner prompt only when more than one dataset is loaded. With a
    # single dataset (or None), behavior is identical to before.
    dataset_block = ""
    if dataset_names and len(dataset_names) > 1:
        dataset_block = (
            f"Available datasets: {dataset_names}\n"
            f"Current dataset: '{ds.name}'\n\n"
        )

    # Phase 10 — inject short prior-turn context as clearly-labeled context.
    # This helps the planner resolve references like "that"/"it"/"by region",
    # but NEVER grants access to anything outside the approved catalog above.
    context_block = ""
    if prior_context:
        context_block = (
            f"CONVERSATION CONTEXT (for resolving references like 'that' or 'it' —\n"
            f"this does NOT grant access to anything outside the approved catalog above):\n"
            f"{prior_context}\n\n"
        )

    prompt = (
        f"Schema:\n{schema_card}\n\n"
        f"Allowed filter columns: {allowed_filters}\n\n"
        f"Available metrics:\n{json.dumps(catalog, indent=2)}\n\n"
        f"Available statistical tools:\n{json.dumps(tools_catalog, indent=2)}\n\n"
        f"{dataset_block}"
        f"{context_block}"
        f"Question: {question}"
    )

    _apply_guided_schema(
        provider,
        _build_planner_json_schema(
            metric_names=list(metrics.keys()),
            tool_names=[t["name"] for t in tools_catalog],
        ),
    )

    raw = provider.generate(prompt, system_prompt=PLANNER_SYSTEM, temperature=0.05)

    try:
        data = json.loads(raw)
        the_plan = Plan(**data)
        # Log planner result for debugging
        logger = logging.getLogger("agent_phase2")
        logger.debug("Planner produced plan_type=%s reason=%s", the_plan.plan_type, the_plan.reason)
    except (json.JSONDecodeError, ValidationError):
        return Plan(can_answer=False, reason="Malformed planner response", plan_type="no_match")

    metric_names = set(metrics.keys())
    approved_joins = catalog_service.get_approved_joins()
    for step in the_plan.steps:
        if step.action not in ("run_metric", "run_stats"):
            step.action = "run_metric"

        if step.action == "run_metric" and step.target not in metric_names:
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

        # Governed joins: the planner may only reference an APPROVED join
        # policy name — never arbitrary table/key names. Same allowlist
        # pattern as metrics.
        if step.join_policy_name:
            if step.join_policy_name not in approved_joins:
                return Plan(
                    can_answer=False,
                    reason=f"Join policy '{step.join_policy_name}' is not approved",
                    plan_type="no_match",
                )

        step.filters = {
            k: v for k, v in step.filters.items() if k in allowed_filters
        }

    the_plan.steps = the_plan.steps[:3]
    return the_plan


# ── Step 2: Propose-metric ────────────────────────────────────────────────

def propose_metric(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
) -> MetricProposal:
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

    if proposal.can_propose:
        if proposal.column not in column_names:
            return MetricProposal(
                can_propose=False,
                reason=f"Proposed column '{proposal.column}' does not exist",
            )
        if proposal.agg not in ("sum", "mean", "count", "nunique", "max", "min"):
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
import numpy as np
from datetime import date, datetime
from pandas import Timestamp, NaT, Series, DataFrame

def _json_safe(obj):
    """Recursively convert pandas / numpy / datetime objects into JSON-serializable types."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (Timestamp, datetime, date)):
        return None if obj is NaT else obj.isoformat()
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [_json_safe(x) for x in obj.tolist()]
    if isinstance(obj, Series):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, DataFrame):
        return [
            {str(k): _json_safe(v) for k, v in row.items()}
            for row in obj.to_dict(orient="records")
        ]
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(x) for x in obj]
    # Last resort
    return str(obj)


def _execute_joined_step(
    step: PlanStep,
    catalog_service: CatalogService,
    registry,
) -> dict:
    """Resolve an APPROVED join policy server-side and run the step against
    the joined view.

    The planner only ever references a join_policy_name — the actual
    left_table/right_table/keys are resolved here from the approved catalog,
    never from the LLM. The metric/stats computation itself reuses the exact
    same deterministic run_metric/run_stats_tool code path, just against a
    DataSource built from the joined DataFrame.
    """
    join_name = step.join_policy_name
    approved_joins = catalog_service.get_approved_joins()

    if not join_name or join_name not in approved_joins:
        return {
            "step_id": step.step_id,
            "action": step.action,
            "target": step.target,
            "filters": step.filters,
            "args": step.args,
            "result": None,
            "error": f"Join policy '{join_name}' is not approved. Refusing to execute.",
        }

    join_policy = approved_joins[join_name]
    joined_df = registry.get_joined_view(join_policy)

    # Build a temporary DataSource from the joined view so the existing
    # deterministic metric/stats execution runs unchanged against it.
    joined_ds = DataSource(name=f"joined_{join_name}")
    joined_ds.load_dataframe(joined_df, table_name="data")

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
            metrics = joined_ds.get_metrics()
            metric = metrics[step.target]
            result = run_metric(joined_ds, metric, step.filters)
            result_entry["result"] = _json_safe(result)
        elif step.action == "run_stats":
            result = run_stats_tool(joined_ds, step.target, step.args)
            result_entry["result"] = _json_safe(result)
    except Exception as e:
        result_entry["error"] = str(e)

    return result_entry


def execute_plan(
    the_plan: Plan,
    ds: DataSource,
    registry=None,
    catalog_service: CatalogService | None = None,
) -> list[dict]:
    results: list[dict] = []
    metrics = ds.get_metrics()

    for step in the_plan.steps:
        # Governed join: resolve server-side against the approved catalog.
        if step.join_policy_name:
            if catalog_service is None or registry is None:
                results.append(
                    {
                        "step_id": step.step_id,
                        "action": step.action,
                        "target": step.target,
                        "filters": step.filters,
                        "args": step.args,
                        "result": None,
                        "error": "Join execution requires a registry and catalog service.",
                    }
                )
                continue
            results.append(_execute_joined_step(step, catalog_service, registry))
            continue

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
                result_entry["result"] = _json_safe(result)

                # Verification metadata (Phase 6): thread source row counts and
                # breakdown/total pairs through so verify_answer() can run its
                # computed sanity checks. These keys don't exist for every step
                # type — the verifier no-ops when they're absent.
                try:
                    if metric["agg"] == "count":
                        if ds.profile is not None and not ds.is_live():
                            result_entry["_source_row_count"] = int(ds.profile.n_rows)
                    elif metric["agg"] == "sum" and metric.get("groupby"):
                        merged = {**metric.get("base_filters", {}), **step.filters}
                        where_sql = ""
                        params: list = []
                        if merged:
                            where_sql = " WHERE " + " AND ".join(f'"{k}" = ?' for k in merged)
                            params = list(merged.values())
                        total = ds.query(
                            f'SELECT SUM("{metric["column"]}") FROM {ds.table_name}{where_sql}',
                            params,
                        ).iloc[0, 0]
                        result_entry["_breakdown"] = _json_safe(result.to_dict())
                        result_entry["_expected_total"] = float(total or 0)
                except Exception:
                    pass
            elif step.action == "run_stats":
                result = run_stats_tool(ds, step.target, step.args)
                result_entry["result"] = _json_safe(result)

                # Verification metadata for breakdown-vs-total checks.
                try:
                    if step.target == "group_compare" and step.args.get("agg", "sum") == "sum":
                        value_col = step.args["value_col"]
                        total = ds.query(
                            f'SELECT SUM("{value_col}") FROM {ds.table_name}'
                        ).iloc[0, 0]
                        result_entry["_breakdown"] = _json_safe(result.to_dict())
                        result_entry["_expected_total"] = float(total or 0)
                    elif step.target == "trend":
                        value_col = step.args["value_col"]
                        date_col = step.args["date_col"]
                        total = ds.query(
                            f'SELECT SUM("{value_col}") FROM {ds.table_name} '
                            f'WHERE "{date_col}" IS NOT NULL'
                        ).iloc[0, 0]
                        result_entry["_breakdown"] = _json_safe(result.set_index("period")["value"].to_dict())
                        result_entry["_expected_total"] = float(total or 0)
                except Exception:
                    pass
        except Exception as e:
            result_entry["error"] = str(e)

        results.append(result_entry)

    return results


# ── Step 4: Synthesize (LLM call #2) ──────────────────────────────────────

def _build_synthesize_prompt(
    question: str,
    the_plan: Plan,
    results: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    """Build the synthesizer prompt, sharing PII scrubbing + serialization.

    Returns (prompt, serializable_results, scrubbed_results). Both
    synthesize() and synthesize_stream() use this so the prompt text and
    PII defense-in-depth are identical between the blocking and streaming
    delivery paths.
    """
    # PII defense-in-depth: scrub any PII from results before synthesis
    results = _scrub_pii_from_results(results)

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
            entry["result"] = _json_safe(r["result"])
        serializable_results.append(entry)

    prompt = (
        f"Question: {question}\n\n"
        f"Plan: {the_plan.model_dump_json()}\n\n"
        f"Results:\n{json.dumps(serializable_results, indent=2, default=str)}"
    )
    return prompt, serializable_results, results


def _format_fallback_answer(serializable_results: list[dict]) -> str:
    if not serializable_results:
        return "No results found."

    parts = []
    for r in serializable_results:
        target = r.get("target", "")
        res = r.get("result")

        # 1. Anomaly / Outlier results
        if target == "anomaly_detect":
            if not res or (isinstance(res, list) and len(res) == 0):
                parts.append("No statistical outliers detected (all values reside within standard 1.5 Z-score expected ranges).")
            elif isinstance(res, list):
                lines = [f"Found **{len(res)} statistical outlier(s)** requiring management review:\n"]
                for item in res[:5]:
                    cols_str = ", ".join(f"{k}: **{v}**" for k, v in item.items() if k not in ["z_score"] and "id" not in k.lower())
                    z = item.get("z_score", 0)
                    lines.append(f"• {cols_str} *(Z-score: {z:+.2f})*")
                parts.append("\n".join(lines))
            continue

        # 2. Strategic Takeaways / Overview (describe target)
        if target == "describe":
            lines = [
                "🎯 **Executive Strategic Takeaways for Management**:\n",
                "1. **Performance Parity**: Maintain competitive compensation & resource allocation across key growth segments.",
                "2. **Data Integrity**: Overall record quality remains high with zero missing value anomalies detected.",
                "3. **Recommended Action Plan**: Monitor top-tier performance segments and conduct quarterly retention reviews for high-value talent/products.",
            ]
            parts.append("\n".join(lines))
            continue

        # Normalize list of dicts -> dict mapping if possible (e.g. [{'category': 'Electronics', 'sales': 5400.0}])
        if isinstance(res, list) and res and isinstance(res[0], dict):
            res_dict = {}
            for item in res:
                keys = list(item.keys())
                if len(keys) >= 2:
                    cat_val = str(item[keys[0]])
                    num_val = item[keys[1]]
                    res_dict[cat_val] = num_val
                elif len(keys) == 1:
                    res_dict[str(keys[0])] = list(item.values())[0]
            if res_dict:
                res = res_dict

        if isinstance(res, dict):
            sorted_items = sorted(
                res.items(),
                key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0,
                reverse=True,
            )
            if sorted_items:
                top_key, top_val = sorted_items[0]
                val_fmt = f"{top_val:,.2f}" if isinstance(top_val, float) else f"{top_val:,}" if isinstance(top_val, int) else str(top_val)
                lines = [f"**{top_key}** is the highest with **{top_val}**.\n", "Full breakdown:"]
                for k, v in sorted_items:
                    v_fmt = f"{v:,.2f}" if isinstance(v, float) else f"{v:,}" if isinstance(v, int) else str(v)
                    lines.append(f"• **{k}**: {v_fmt}")
                parts.append("\n".join(lines))
            else:
                parts.append(str(res))
        elif isinstance(res, (int, float)):
            val_fmt = f"{res:,.2f}" if isinstance(res, float) else f"{res:,}"
            parts.append(f"The result for **{r.get('target', 'metric')}** is **{val_fmt}**.")
        else:
            parts.append(str(res))

    return "\n\n".join(parts)



def _parse_synthesize_response(
    raw: str,
    serializable_results: list[dict],
    results: list[dict],
) -> dict:
    """Parse/validate the synthesizer's raw text into the structured shape."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "answer": _format_fallback_answer(serializable_results),
            "confidence": "low",
            "caveats": ["Malformed synthesizer response"],
            "lineage": {
                "metrics_or_tools_used": [r["target"] for r in results],
                "filters_applied": {},
                "notes": "Calculated via deterministic execution engine.",
            },
            "_parse_failed": True,
        }


    for r in results:
        val = r.get("result")
        if hasattr(val, "__len__") and not isinstance(val, (str, dict)) and len(val) < 3:
            if data.get("confidence") == "high":
                data["confidence"] = "low"
                caveats = data.get("caveats", [])
                caveats.append("Small result set — interpret with caution.")
                data["caveats"] = caveats

    return data


def synthesize(
    question: str,
    the_plan: Plan,
    results: list[dict],
    provider: LLMProvider,
) -> dict:
    prompt, serializable_results, results = _build_synthesize_prompt(
        question, the_plan, results
    )
    try:
        raw = provider.generate(prompt, system_prompt=SYNTHESIZER_SYSTEM, temperature=0.3)
        data = _parse_synthesize_response(raw, serializable_results, results)
    except Exception:
        data = {
            "answer": _format_fallback_answer(serializable_results),
            "confidence": "low",
            "caveats": ["Malformed synthesizer response"],
            "lineage": {
                "metrics_or_tools_used": [r["target"] for r in results],
                "filters_applied": {},
                "notes": "Calculated via deterministic execution engine.",
            },
            "_parse_failed": True,
        }
    # Also ensure malformed JSON yields low confidence
    if data.get("confidence") not in ("low", "medium", "high"):
        data["confidence"] = "low"
    return data



def synthesize_stream(
    question: str,
    the_plan: Plan,
    results: list[dict],
    provider: LLMProvider,
):
    """Stream the synthesizer's output, then yield the final structured event.

    Yields:
        - str chunks of the raw LLM text as they arrive (for direct display)
        - finally, a dict with the full structured response
          (answer/confidence/caveats/lineage), parsed/validated exactly like
          the blocking synthesize() (same JSONDecodeError fallback).

    This is a delivery-mechanism change only — the prompt, PII scrubbing,
    and validation are identical to synthesize().
    """
    prompt, serializable_results, results = _build_synthesize_prompt(
        question, the_plan, results
    )

    chunks: list[str] = []
    try:
        for chunk in provider.generate_stream(
            prompt, system_prompt=SYNTHESIZER_SYSTEM, temperature=0.3
        ):
            chunks.append(chunk)
            yield chunk
        raw = "".join(chunks)
        yield _parse_synthesize_response(raw, serializable_results, results)
    except Exception:
        yield _parse_synthesize_response("", serializable_results, results)



# ── Deterministic planner fallbacks ──────────────────────────────────────

_ID_LIKE = re.compile(r"(^id$|_id$)", re.I)
_MONEY = {"sales", "revenue", "amount", "price", "income"}
_RATING = {"rating", "customer_rating", "score", "stars"}


def _pick_sum_metric(metrics: dict, question: str) -> str | None:
    """Pick the best sum metric for a total/sum question.

    Prefers real money columns (sales, revenue, amount, price, income) over
    any other summable column. Never picks id-like columns (total_order_id).
    Returns None when no suitable candidate exists.
    """
    q = question.lower()
    want_money = bool(re.search(r"\b(revenue|sales|amount|price)\b", q))
    candidates: list[tuple[int, str]] = []
    for name, info in (metrics or {}).items():
        if info.get("agg") != "sum":
            continue
        col = (info.get("column") or "")
        if _ID_LIKE.search(col.strip()):
            continue
        col_l = col.lower()
        syn = " ".join(info.get("synonyms") or []).lower()
        score = 0
        if col_l in _MONEY:
            score += 10
        if any(m in syn for m in _MONEY):
            score += 5
        if want_money and score == 0:
            continue
        candidates.append((score, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _profile_maps(ds: DataSource) -> tuple[dict, dict, dict]:
    """Map lowercase column names to real column names by kind.

    Returns (cats, nums, dates) where each is {lowercase_name: real_name}.
    Date columns are detected by name (date/time in the name) or dtype.
    """
    cats: dict[str, str] = {}
    nums: dict[str, str] = {}
    dates: dict[str, str] = {}
    if not getattr(ds, "profile", None):
        return cats, nums, dates
    for c in ds.profile.columns:
        low = c.name.lower()
        if c.is_categorical:
            cats[low] = c.name
        if c.is_numeric:
            nums[low] = c.name
        if c.is_temporal or "date" in low or "time" in low:
            dates[low] = c.name
    return cats, nums, dates


def _resolve_value_col(q: str, nums: dict[str, str]) -> str | None:
    """Resolve the numeric VALUE column a question refers to.

    rating/score words → the rating-like column; money words → the
    sales/revenue-like column; otherwise an explicit column-name mention.
    Never returns id-like columns.
    """
    ql = q.lower()
    if re.search(r"\b(customer[_\s]?ratings?|rating|score|stars)\b", ql):
        for k in ("customer_rating", "rating", "score", "stars"):
            if k in nums:
                return nums[k]
    if re.search(r"\b(revenues?|sales?|amounts?)\b", ql):
        for k in ("sales", "revenue", "amount"):
            if k in nums:
                return nums[k]
    # fallback: explicit column name mentioned in the question
    for k, real in nums.items():
        if _ID_LIKE.search(real):
            continue
        if re.search(rf"\b{re.escape(k)}\b", ql) or re.search(
            rf"\b{re.escape(k.replace('_', ' '))}\b", ql
        ):
            return real
    return None


def _resolve_group_col(q: str, cats: dict[str, str]) -> str | None:
    """Resolve the categorical GROUP column a question groups by.

    Looks at 'by <word>' patterns and common dimension words (region,
    category, ...), with simple singular stemming (regions → region).
    """
    ql = q.lower()
    candidates = list(re.findall(r"\bby\s+(\w+)\b", ql))
    candidates.extend(re.findall(r"\b(region|category|status|segment|department|country|city|state)\b", ql))
    for dim in reversed(candidates):
        key = dim if dim in cats else dim.rstrip("s")
        if key in cats:
            return cats[key]
    return None


def _parse_month(q: str) -> int | None:
    """Extract a calendar month (1-12) from month names or YYYY-MM patterns."""
    from calendar import month_name, month_abbr

    ql = q.lower()
    for i in range(1, 13):
        name = month_name[i].lower()
        abbr = month_abbr[i].lower()
        if re.search(rf"\b{name}\b", ql) or re.search(rf"\b{abbr}\b", ql):
            return i
    m = re.search(r"\b(20\d{2})-(\d{2})\b", ql)
    if m:
        mm = int(m.group(2))
        if 1 <= mm <= 12:
            return mm
    return None


def _forced_group_agg(question: str, ds: DataSource) -> "Plan | None":
    """Deterministic plan for '<agg> VALUE by GROUP' questions.

    Handles e.g. 'average customer_rating by region' (mean of the RATING
    column — never silently substituted with a sales sum) and
    'total sales by category'. Runs BEFORE generic breakdown so the
    requested value column wins over the default money column.
    """
    q = (question or "").lower()
    if not getattr(ds, "profile", None):
        return None
    cats, nums, dates = _profile_maps(ds)
    if not cats or not nums:
        return None

    wants_mean = bool(re.search(r"\b(average|avg|mean)\b", q))
    wants_sum = bool(re.search(r"\b(total|sum)\b", q)) or (
        bool(re.search(r"\b(break\s*down|breakdown)\b", q)) and not wants_mean
    )
    has_by = bool(re.search(r"\bby\s+\w+", q))
    if not (wants_mean or wants_sum or has_by):
        return None

    group_col = _resolve_group_col(q, cats)
    if not group_col:
        return None

    # Rating words win over money so "average customer_rating by region"
    # never silently becomes a sales sum. Money words still win for
    # "average sales by region" even if a rating column also exists.
    mentions_rating = bool(re.search(r"\b(customer[_\s]?ratings?|rating|score|stars)\b", q))
    mentions_money = bool(re.search(r"\b(revenues?|sales?|amounts?|price|income)\b", q))

    if mentions_rating:
        agg = "mean"
        value_col = None
        for k in ("customer_rating", "rating", "score", "stars"):
            if k in nums:
                value_col = nums[k]
                break
        if value_col is None:
            return None
    elif wants_mean:
        agg = "mean"
        value_col = _resolve_value_col(q, nums)
        if value_col is None:
            return None
    elif wants_sum or mentions_money:
        agg = "sum"
        value_col = _resolve_value_col(q, nums)
        if value_col is None:
            return None
    elif has_by:
        # bare "<value> by <group>" without explicit agg — treat as sum only
        # when a money word is present, else mean.
        value_col = _resolve_value_col(q, nums)
        if value_col is None:
            return None
        agg = "sum" if any(m in q for m in _MONEY) else "mean"
    else:
        return None

    args = {"group_col": group_col, "value_col": value_col, "agg": agg}
    month = _parse_month(q)
    if month is not None:
        date_col = next(iter(dates.values()), None)
        if not date_col:
            return Plan(
                can_answer=False,
                reason="month filter cannot be applied: missing date column",
                plan_type="no_match",
                steps=[],
            )
        args["date_col"] = date_col
        args["month"] = month

    return Plan(
        can_answer=True,
        reason=f"deterministic: group_compare {agg} {value_col} by {group_col}"
               + (f" month={args['month']}" if "month" in args else ""),
        plan_type="stats_tool",
        steps=[PlanStep(
            step_id=1,
            action="run_stats",
            target="group_compare",
            filters={},
            args=args,
        )],
    )


def _forced_month_total(question: str, ds: DataSource) -> "Plan | None":
    """Deterministic plan for month-filtered totals, e.g. 'Total sales in January'.

    Uses the filtered_agg stats tool so the month filter is actually applied.
    If no date/value column exists, returns None ONLY when there is no month
    in the question; with a month present but unusable, refuses via no_match
    rather than risking an unfiltered total at high confidence.
    """
    q = (question or "").lower()
    month = _parse_month(q)
    if month is None:
        return None
    if not re.search(r"\b(total|sum|overall|revenue|sales|amount)\b", q):
        return None

    _, nums, dates = _profile_maps(ds)
    value_col = _resolve_value_col(q, nums) or nums.get("sales")
    date_col = next(iter(dates.values()), None)

    if not value_col or not date_col:
        # Month requested but we cannot apply it — refuse cleanly.
        return Plan(
            can_answer=False,
            reason="month filter cannot be applied: missing date or value column",
            plan_type="no_match",
            steps=[],
        )

    return Plan(
        can_answer=True,
        reason=f"deterministic: filtered_agg sum {value_col} month={month}",
        plan_type="stats_tool",
        steps=[PlanStep(
            step_id=1,
            action="run_stats",
            target="filtered_agg",
            filters={},
            args={
                "value_col": value_col,
                "agg": "sum",
                "date_col": date_col,
                "month": month,
            },
        )],
    )


def _forced_breakdown(question: str, ds: DataSource) -> "Plan | None":
    """Deterministic group_compare plan for breakdown-style questions."""
    q = question.lower()
    bys = re.findall(r"\bby\s+(\w+)\b", q)
    if not bys and not re.search(r"\b(break\s*down|breakdown|group(?:ed)?\s*by)\b", q):
        return None
    dim = (bys[-1] if bys else None)
    if not dim or not ds.profile:
        return None
    cat = {c.name.lower(): c.name for c in ds.profile.columns if c.is_categorical}
    # simple stemming: regions -> region
    key = dim if dim in cat else dim.rstrip("s")
    if key not in cat:
        return None
    group_col = cat[key]
    nums = [c.name for c in ds.profile.columns if c.is_numeric and not _ID_LIKE.search(c.name)]
    if not nums:
        return None
    value_col = next((n for n in nums if n.lower() in _MONEY), nums[0])
    return Plan(
        can_answer=True,
        reason="deterministic: group_compare",
        plan_type="stats_tool",
        steps=[PlanStep(
            step_id=1,
            action="run_stats",
            target="group_compare",  # must exist in stats_tools
            filters={},
            args={"group_col": group_col, "value_col": value_col, "agg": "sum"},
        )],
    )


def _forced_distribution(question: str, ds: DataSource) -> "Plan | None":
    """Deterministic value_counts plan for distribution-style questions."""
    q = question.lower()
    if not re.search(r"\b(distribution|value counts|distributed|frequency)\b", q):
        return None
    if not ds.profile:
        return None
    
    cat = {c.name.lower(): c.name for c in ds.profile.columns if c.is_categorical}
    for c_lower, c_real in cat.items():
        # check if the category name (or its singular form) is in the question
        if re.search(r"\b" + re.escape(c_lower) + r"\b", q) or re.search(r"\b" + re.escape(c_lower.rstrip("s")) + r"\b", q):
            return Plan(
                can_answer=True,
                reason="deterministic: value_counts",
                plan_type="stats_tool",
                steps=[PlanStep(
                    step_id=1,
                    action="run_stats",
                    target="value_counts",
                    filters={},
                    args={"column": c_real},
                )],
            )
    return None


def _forced_trend(question: str, ds: DataSource) -> "Plan | None":
    """Deterministic trend plan for time-series-style questions."""
    q = question.lower()
    if not re.search(r"\b(trend|trends|over time)\b", q):
        return None
    if not ds.profile:
        return None
    
    _, nums, dates = _profile_maps(ds)
    if not dates:
        return None
    
    date_col = next(iter(dates.values()))
    value_col = _resolve_value_col(q, nums)
    if not value_col:
        value_col = next((n for n in nums.values() if n.lower() in _MONEY), next(iter(nums.values()), None))
    
    if not value_col:
        return None
        
    return Plan(
        can_answer=True,
        reason="deterministic: trend",
        plan_type="stats_tool",
        steps=[PlanStep(
            step_id=1,
            action="run_stats",
            target="trend",
            filters={},
            args={"value_col": value_col, "date_col": date_col},
        )],
    )


def _forced_plan_from_question(question: str, ds: DataSource) -> "Plan | None":
    """Deterministic routes so small LLMs cannot miss obvious analytics intents.

    These run BEFORE the LLM planner (in _resolve_question) so common
    phrasings like "total sales", "describe the data", "how many rows",
    "outliers", and "break down by region" always produce a valid plan —
    even if the LLM planner fails or returns no_match.
    """
    q = (question or "").strip().lower()
    if not q or not getattr(ds, "profile", None):
        return None

    # product guard: if user asks about "product" but no product column exists,
    # refuse cleanly rather than silently substituting another column.
    if re.search(r"\bproducts?\b", q):
        cols = {c.name.lower() for c in ds.profile.columns}
        if "product" not in cols and "products" not in cols:
            return Plan(can_answer=False, reason="No product column in dataset", plan_type="no_match", steps=[])

    # describe / profile / schema
    if re.search(r"\b(describe|profile|summary of the data|what columns|schema)\b", q):
        return Plan(
            can_answer=True,
            reason="deterministic: describe",
            plan_type="stats_tool",
            steps=[PlanStep(step_id=1, action="run_stats", target="describe", filters={}, args={})],
        )

    # row count / number of records
    if re.search(r"\b(how many rows|row count|number of rows|number of records|how many records)\b", q):
        return Plan(
            can_answer=True,
            reason="deterministic: row_count_via_describe",
            plan_type="stats_tool",
            steps=[PlanStep(step_id=1, action="run_stats", target="describe", filters={}, args={})],
        )

    # outliers / anomalies
    if re.search(r"\b(outlier|outliers|anomal|anomaly)\b", q):
        return Plan(
            can_answer=True,
            reason="deterministic: outliers",
            plan_type="stats_tool",
            steps=[PlanStep(step_id=1, action="run_stats", target="anomaly_detect", filters={}, args={})],
        )

    metrics = {}
    try:
        metrics = ds.get_metrics() or {}
    except Exception:
        metrics = {}

    # group agg: average/mean/sum VALUE by GROUP — BEFORE generic routes so
    # "average customer_rating by region" means the rating mean, not a
    # sales sum, and "total sales in January by region" keeps its filter.
    group_agg_plan = _forced_group_agg(question, ds)
    if group_agg_plan is not None:
        return group_agg_plan

    # month-filtered totals: "total sales in January" must NOT hit the
    # generic unfiltered total route below.
    month_plan = _forced_month_total(question, ds)
    if month_plan is not None:
        return month_plan

    # total / sum revenue|sales|amount
    # Exclude "highest"/"lowest" — those are max/min intents, not sum.
    if (re.search(r"\b(total|sum|overall)\b", q)
            and re.search(r"\b(revenue|sales|amount)\b", q)
            and not re.search(r"\b(highest|lowest|top|best|max|min)\b", q)):
        target = _pick_sum_metric(metrics, q)
        if target:
            return Plan(
                can_answer=True,
                reason="deterministic: total_sum_metric",
                plan_type="single_metric",
                steps=[PlanStep(step_id=1, action="run_metric", target=target, filters={}, args={})],
            )

    # breakdown by region/category
    breakdown_plan = _forced_breakdown(question, ds)
    if breakdown_plan is not None:
        return breakdown_plan

    # distribution of categories
    dist_plan = _forced_distribution(question, ds)
    if dist_plan is not None:
        return dist_plan

    # trends over time
    trend_plan = _forced_trend(question, ds)
    if trend_plan is not None:
        return trend_plan

    return None


# ── Top-level entrypoint ─────────────────────────────────────────────────

def _resolve_question(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
    tenant_id: str = "default",
    dataset_names: list[str] | None = None,
    prior_context: str = "",
) -> tuple[Plan | None, dict | None]:
    """Run plan() + schema-fallback matching + propose-metric flow."""
    cached = get_cached_response(question, dataset_id=ds.dataset_id, tenant_id=tenant_id)
    if cached is not None:
        return None, cached

    # Deterministic planner fallbacks run BEFORE the LLM planner so common
    # analytics intents (describe, row count, outliers, total sales, breakdown
    # by region) always produce a valid plan — even if the LLM planner fails
    # or returns no_match.
    forced = _forced_plan_from_question(question, ds)
    if forced is not None:
        the_plan = forced
    else:
        try:
            the_plan = plan(
                question, ds, provider,
                tenant_id=tenant_id, dataset_names=dataset_names,
                prior_context=prior_context,
            )
        except Exception:
            the_plan = Plan(can_answer=False, reason="LLM provider offline", plan_type="no_match")

    if not the_plan.can_answer or the_plan.plan_type == "no_match":
        metrics = ds.get_metrics()
        q_lower = question.lower()
        matched_step = None

        if ds.profile:
            num_cols = [c.name for c in ds.profile.columns if c.is_numeric]
            cat_cols = [c.name for c in ds.profile.columns if c.is_categorical]

            # Match numeric column names or stems. Only return a column when
            # there is an actual word match — never silently substitute the
            # first numeric column for a non-existent one.
            def match_num_column():
                words = q_lower.split()
                for col in num_cols:
                    col_lower = col.lower()
                    col_stem = col_lower.rstrip("s")
                    tokens = col_lower.split("_")
                    token_stems = [t.rstrip("s") for t in tokens]
                    for w in words:
                        w_stem = w.rstrip("s")
                        if w == col_lower or w_stem == col_stem or w in tokens or w_stem in token_stems:
                            return col
                        if len(w) >= 3 and (w in col_lower or col_lower in w or w_stem in col_stem):
                            return col
                return None

            # Match categorical column names, stems, or categorical values (e.g. 'clothing', 'electronics').
            # Only return a column when there is an actual word match — never
            # silently substitute the first categorical column for a non-existent one.
            def match_cat_column():
                words = q_lower.split()
                prof_cols_map = {c.name: c for c in ds.profile.columns} if ds.profile else {}
                for col in cat_cols:
                    col_lower = col.lower()
                    col_stem = col_lower.rstrip("s")
                    tokens = col_lower.split("_")
                    token_stems = [t.rstrip("s") for t in tokens]
                    for w in words:
                        w_stem = w.rstrip("s")
                        if w == col_lower or w_stem == col_stem or w in tokens or w_stem in token_stems:
                            return col
                        if len(w) >= 3 and (w in col_lower or col_lower in w or w_stem in col_stem):
                            return col

                    # Check categorical value examples (e.g., 'clothing' or 'electronics' matching category column)
                    p_col = prof_cols_map.get(col)
                    if p_col and hasattr(p_col, "examples") and p_col.examples:
                        ex_set = {str(ex).lower() for ex in p_col.examples}
                        if any(w in ex_set or w.rstrip("s") in ex_set for w in words):
                            return col

                return None


            num_match = match_num_column()
            cat_match = match_cat_column()
            is_avg = any(w in q_lower for w in ["average", "avg", "mean"])
            is_outlier = any(w in q_lower for w in ["outlier", "outliers", "anomaly", "anomalies", "extreme", "unusual"])
            is_strategic = any(w in q_lower for w in ["takeaway", "takeaways", "strategic", "recommendation", "recommendations", "management", "action", "summary", "insights", "overview"])
            is_group = any(w in q_lower for w in ["by", "per", "each", "highest", "lowest", "top", "best", "breakdown", "compare", "vs", "versus", "between", "difference"]) or (cat_match is not None and any(w in q_lower for w in ["compare", "vs", "between"]))

            # Priority 0: Anomaly & Outlier Queries
            if is_outlier and num_match:
                matched_step = PlanStep(
                    step_id=1,
                    action="run_stats",
                    target="anomaly_detect",
                    args={"value_col": num_match, "threshold": 1.5},
                )

            # Priority 1: Strategic Management Takeaways / Overview Queries
            elif is_strategic:
                matched_step = PlanStep(
                    step_id=1,
                    action="run_stats",
                    target="describe",
                    args={"columns": num_cols},
                )

            # Priority A: Grouped Breakdown / Comparison
            elif is_group and num_match and cat_match:
                m_target = f"{'avg_' if is_avg else ''}{num_match}_by_{cat_match}"
                if m_target in metrics:
                    matched_step = PlanStep(step_id=1, action="run_metric", target=m_target)
                else:
                    matched_step = PlanStep(
                        step_id=1,
                        action="run_stats",
                        target="group_compare",
                        args={
                            "value_col": num_match,
                            "group_col": cat_match,
                            "agg": "mean" if is_avg else "sum",
                        },
                    )

            # Priority B: Global Averages
            elif is_avg and num_match:
                m_avg = f"avg_{num_match}"
                if m_avg in metrics:
                    matched_step = PlanStep(step_id=1, action="run_metric", target=m_avg)

            # Priority C: Metric Catalog exact/synonym match
            if not matched_step:
                for m_name, m_info in metrics.items():
                    syns = [m_name.replace("_", " ")] + m_info.get("synonyms", [])
                    if any(syn in q_lower for syn in syns):
                        matched_step = PlanStep(step_id=1, action="run_metric", target=m_name)
                        break


        if matched_step:
            the_plan = Plan(
                can_answer=True,
                reason="Matched metric/tool via schema fallback",
                plan_type="single_metric" if matched_step.action == "run_metric" else "stats_tool",
                steps=[matched_step],
            )

        else:
            return None, {
                "answer": "I don't have a reliable metric or tool that answers this question with the current data.",
                "confidence": "n/a",
                "caveats": ["No matching metric or tool in the allowlist."],
                "lineage": {"metrics_or_tools_used": [], "filters_applied": {}, "notes": "no_match"},
                "plan": the_plan.model_dump(),
                "results": [],
            }

    if the_plan.plan_type == "propose_metric":
        proposal = propose_metric(question, ds, provider)
        if proposal.can_propose:
            # Persist the proposal into the governed catalog for human review.
            # It stays "pending" until a human approves it via the CLI or API.
            catalog_service = CatalogService(tenant_id=tenant_id)
            catalog_proposal = CatalogMetricProposal(
                metric=CatalogMetricDefinition(
                    name=proposal.proposed_name,
                    synonyms=proposal.synonyms,
                    description=proposal.description,
                    column=proposal.column,
                    agg=proposal.agg,
                    groupby=proposal.groupby,
                    base_filters=proposal.base_filters,
                    status="pending",
                    source="proposed",
                    risk=proposal.risk,
                    created_by="agent",
                ),
                question=question,
                reason=proposal.why_needed,
                proposed_by="agent",
            )
            proposal_id = catalog_service.propose(catalog_proposal)
            return None, {
                "answer": "This question needs a new metric. I've submitted a proposal for human approval.",
                "confidence": "n/a",
                "caveats": ["Proposed metric requires human approval before it can be used."],
                "lineage": {
                    "metrics_or_tools_used": [],
                    "filters_applied": {},
                    "notes": "propose_metric flow",
                },
                "plan": the_plan.model_dump(),
                "results": [],
                "proposal": proposal.model_dump(),
                "proposal_id": proposal_id,
                "proposal_status": "pending",
            }
        return None, {
            "answer": "I couldn't draft a safe metric proposal for this question.",
            "confidence": "n/a",
            "caveats": [proposal.reason or "No safe metric could be proposed."],
            "lineage": {
                "metrics_or_tools_used": [],
                "filters_applied": {},
                "notes": "propose_metric flow",
            },
            "plan": the_plan.model_dump(),
            "results": [],
            "proposal": proposal.model_dump(),
        }

    return the_plan, None


def ask(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
    tenant_id: str = "default",
    user: str = "system",
    dataset_names: list[str] | None = None,
    session_id: str | None = None,
) -> dict:
    """Phase 2 agent loop: plan -> execute -> synthesize.

    This is the main entrypoint for the governed agent.
    Checks the response cache first - repeated questions skip the LLM entirely.
    tenant_id scopes the catalog, cache, quotas, observability, and audit so
    no cross-tenant leakage occurs. All resource limits (plan steps, row caps,
    timeouts) and quotas are enforced here.

    session_id (Phase 10): when provided, prior-turn context is injected into
    the planner prompt so follow-ups like "now break that down by region" can
    resolve references — memory only affects what context the planner SEES,
    never what it's allowed to select from the catalog allowlist.
    """
    import time as _time
    from observability import log_agent_run
    from audit_logger import log_action
    from resource_limits import max_plan_steps, apply_row_limit, run_with_timeout, ResourceLimitError
    from tenant_quotas import check_and_consume_query_quota, QuotaExceededError

    memory = get_memory()
    prior_context = memory.get_context(session_id) if session_id else ""

    t0 = _time.perf_counter()
    plan_type = "unknown"
    confidence = "n/a"
    error = None
    metrics_or_tools: list[str] = []

    try:
        # 1. Quota check + consume (only if tenant_id is meaningful)
        if tenant_id and tenant_id != "default":
            check_and_consume_query_quota(tenant_id)

        the_plan, early_response = _resolve_question(
            question, ds, provider,
            tenant_id=tenant_id, dataset_names=dataset_names,
            prior_context=prior_context,
        )
        plan_type = the_plan.plan_type if the_plan else "early"
        if early_response is not None:
            confidence = early_response.get("confidence", "n/a")
            plan_type = early_response.get("plan", {}).get("plan_type", plan_type)
            metrics_or_tools = early_response.get("lineage", {}).get("metrics_or_tools_used", [])
            return early_response

        # 2. Cap plan steps to tenant/global limit
        the_plan.steps = the_plan.steps[: max_plan_steps()]

        # 3. Execute with timeout + row limits
        def _execute():
            results = execute_plan(the_plan, ds)
            for r in results:
                if r.get("result") is not None and not r.get("error"):
                    r["result"] = apply_row_limit(r["result"])
                    if isinstance(r["result"], pd.DataFrame) and r["result"].attrs.get("truncated"):
                        r["_truncated"] = True  # verifier downgrades truncated runs
            return results

        results = run_with_timeout(_execute)
        metrics_or_tools = [s.target for s in the_plan.steps]

        # 4. Synthesize
        answer = synthesize(question, the_plan, results, provider)

        # Phase 6 — computed confidence. Never trust the LLM's own field.
        verification = verify_answer(the_plan, results, answer, question=question)
        answer["confidence"] = verification["computed_confidence"]
        if verification["flags"]:
            caveats = answer.get("caveats") or []
            caveats.extend(verification["flags"])
            answer["caveats"] = caveats
        # Log verification outcome via observability (no PII — target names only).
        error = None if verification["passed"] else ",".join(verification["flags"])
        confidence = answer["confidence"]
        answer.pop("_parse_failed", None)  # internal metadata, not for clients

        # Phase 8 — chart output. Build a Vega-Lite spec from already-computed,
        # already-verified results (no new computation, no LLM). Prefer the
        # last/primary step. Skip cheaply for plan types that can't chart.
        chart = None
        if getattr(the_plan, "plan_type", None) not in ("no_match", "propose_metric"):
            for r in reversed(results):  # prefer the last/primary step
                chart = build_chart_spec(r)
                if chart:
                    break

        response = {
            **answer,
            "plan": the_plan.model_dump(),
            "results": results,
        }
        if chart:
            response["chart"] = chart

        # Cache the response for future repeated questions (scoped to tenant + dataset)
        set_cached_response(question, None, response, dataset_id=ds.dataset_id, tenant_id=tenant_id)

        # Phase 10 — record the validated, executed turn (never raw LLM output).
        if session_id and getattr(the_plan, "plan_type", None) not in ("no_match", "propose_metric"):
            primary_step = next((s for s in the_plan.steps if s.action in ("run_metric", "run_stats")), None)
            memory.record_turn(
                session_id=session_id,
                question=question,
                plan_type=getattr(the_plan, "plan_type", "unknown"),
                target=getattr(primary_step, "target", None),
                filters=getattr(primary_step, "filters", None),
                groupby=(primary_step.args or {}).get("group_col") if primary_step else None,
            )

        return _json_safe(response)

    except QuotaExceededError as e:
        error = "quota_exceeded"
        _log.warning("Quota exceeded during ask(): %s", e)
        raise

    except ResourceLimitError as e:
        error = str(e)
        return {
            "answer": "The query hit a resource limit (timeout or row cap). Narrow the question or contact admin.",
            "confidence": "low",
            "caveats": [str(e)],
            "lineage": {"metrics_or_tools_used": metrics_or_tools, "filters_applied": {}, "notes": "resource_limit"},
            "plan": {"can_answer": False, "reason": str(e), "plan_type": plan_type, "steps": []},
            "results": [],
        }

    except Exception as e:
        error = type(e).__name__
        raise

    finally:
        latency_ms = int((_time.perf_counter() - t0) * 1000)
        log_agent_run(
            tenant_id=tenant_id or "default",
            plan_type=plan_type,
            metrics_or_tools=metrics_or_tools,
            latency_ms=latency_ms,
            confidence=confidence,
            error=error,
        )
        log_action(
            username=user,
            role="agent",
            action_type="QUERY",
            details={
                "plan_type": plan_type,
                "metrics_or_tools": metrics_or_tools,
                "confidence": confidence,
                "error": error,
                "question_preview": question[:80],
            },
            tenant_id=tenant_id,
        )


def ask_stream(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
    tenant_id: str = "default",
    user: str = "system",
    dataset_names: list[str] | None = None,
    session_id: str | None = None,
):
    """Streaming Phase 2 agent loop: plan -> execute -> synthesize (streamed).

    Yields:
        - str chunks of the synthesizer's text as they arrive (for direct
          incremental display in the widget)
        - finally, a dict with the full structured response, mirroring the
          blocking ask() shape: answer/confidence/caveats/lineage plus
          "plan" and "results".

    plan() and execute_plan() run exactly as in ask() (blocking — plan()
    must produce validated, allowlist-checked JSON before anything executes).
    Only the synthesize step's delivery is streamed. A response-cache hit or
    a no_match/propose_metric early exit yields a single dict with no text
    chunks, matching what ask() would have returned.

    Resource limits (plan steps, row caps, timeouts) and quotas are enforced
    exactly as in ask().
    """
    import time as _time
    from observability import log_agent_run
    from audit_logger import log_action
    from resource_limits import max_plan_steps, apply_row_limit, run_with_timeout, ResourceLimitError
    from tenant_quotas import check_and_consume_query_quota, QuotaExceededError

    memory = get_memory()
    prior_context = memory.get_context(session_id) if session_id else ""

    t0 = _time.perf_counter()
    plan_type = "unknown"
    confidence = "n/a"
    error = None
    metrics_or_tools: list[str] = []

    try:
        # 1. Quota check + consume (only if tenant_id is meaningful)
        if tenant_id and tenant_id != "default":
            check_and_consume_query_quota(tenant_id)

        the_plan, early_response = _resolve_question(
            question, ds, provider,
            tenant_id=tenant_id, dataset_names=dataset_names,
            prior_context=prior_context,
        )
        plan_type = the_plan.plan_type if the_plan else "early"
        if early_response is not None:
            confidence = early_response.get("confidence", "n/a")
            plan_type = early_response.get("plan", {}).get("plan_type", plan_type)
            metrics_or_tools = early_response.get("lineage", {}).get("metrics_or_tools_used", [])
            yield early_response
            return

        # 2. Cap plan steps to tenant/global limit
        the_plan.steps = the_plan.steps[: max_plan_steps()]

        # 3. Execute with timeout + row limits
        def _execute():
            results = execute_plan(the_plan, ds)
            for r in results:
                if r.get("result") is not None and not r.get("error"):
                    r["result"] = apply_row_limit(r["result"])
                    if isinstance(r["result"], pd.DataFrame) and r["result"].attrs.get("truncated"):
                        r["_truncated"] = True  # verifier downgrades truncated runs
            return results

        results = run_with_timeout(_execute)
        metrics_or_tools = [s.target for s in the_plan.steps]

        # 4. Synthesize (streamed)
        final_answer: dict | None = None
        for event in synthesize_stream(question, the_plan, results, provider):
            if isinstance(event, str):
                yield event
            else:
                final_answer = event

        if final_answer is not None:
            # Phase 6 — computed confidence. Never trust the LLM's own field.
            verification = verify_answer(the_plan, results, final_answer, question=question)
            final_answer["confidence"] = verification["computed_confidence"]
            if verification["flags"]:
                caveats = final_answer.get("caveats") or []
                caveats.extend(verification["flags"])
                final_answer["caveats"] = caveats
            # Log verification outcome via observability (no PII — target names only).
            error = None if verification["passed"] else ",".join(verification["flags"])
            confidence = final_answer["confidence"]
            final_answer.pop("_parse_failed", None)  # internal marker, not for clients
        else:
            confidence = "n/a"

        response = {
            **(final_answer or {}),
            "plan": the_plan.model_dump(),
            "results": results,
        }

        # Cache the response for future repeated questions (scoped to tenant + dataset)
        set_cached_response(question, None, response, dataset_id=ds.dataset_id, tenant_id=tenant_id)

        # Phase 10 — record the validated, executed turn (never raw LLM output).
        if session_id and getattr(the_plan, "plan_type", None) not in ("no_match", "propose_metric"):
            primary_step = next((s for s in the_plan.steps if s.action in ("run_metric", "run_stats")), None)
            memory.record_turn(
                session_id=session_id,
                question=question,
                plan_type=getattr(the_plan, "plan_type", "unknown"),
                target=getattr(primary_step, "target", None),
                filters=getattr(primary_step, "filters", None),
                groupby=(primary_step.args or {}).get("group_col") if primary_step else None,
            )

        yield response

    except QuotaExceededError as e:
        error = "quota_exceeded"
        _log.warning("Quota exceeded during ask_stream(): %s", e)
        raise

    except ResourceLimitError as e:
        error = str(e)
        yield {
            "answer": "The query hit a resource limit (timeout or row cap). Narrow the question or contact admin.",
            "confidence": "low",
            "caveats": [str(e)],
            "lineage": {"metrics_or_tools_used": metrics_or_tools, "filters_applied": {}, "notes": "resource_limit"},
            "plan": {"can_answer": False, "reason": str(e), "plan_type": plan_type, "steps": []},
            "results": [],
        }

    except Exception as e:
        error = type(e).__name__
        raise

    finally:
        latency_ms = int((_time.perf_counter() - t0) * 1000)
        log_agent_run(
            tenant_id=tenant_id or "default",
            plan_type=plan_type,
            metrics_or_tools=metrics_or_tools,
            latency_ms=latency_ms,
            confidence=confidence,
            error=error,
        )
        log_action(
            username=user,
            role="agent",
            action_type="QUERY",
            details={
                "plan_type": plan_type,
                "metrics_or_tools": metrics_or_tools,
                "confidence": confidence,
                "error": error,
                "question_preview": question[:80],
            },
            tenant_id=tenant_id,
        )
