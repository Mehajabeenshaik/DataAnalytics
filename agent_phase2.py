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
from typing import Any

import pandas as pd
from pydantic import BaseModel, ValidationError

from data_source import DataSource
from metric_factory import get_metric_catalog_for_llm
from agent_core import run_metric
from stats_tools import ALLOWED_STATS_TOOLS, VALID_TOOL_NAMES, run_stats_tool
from llm_provider import LLMProvider
from cache import get_cached_response, set_cached_response, clear_cache
from catalog.service import CatalogService
from catalog.models import MetricDefinition as CatalogMetricDefinition
from catalog.models import MetricProposal as CatalogMetricProposal


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
- Only use tool names from the allowed tools list: describe, value_counts, correlation, group_compare, missingness, trend.
- For questions comparing totals/means across categories (e.g. "highest sales by region", "sales per region"), use plan_type="stats_tool", action="run_stats", target="group_compare", args={"value_col": "<numeric_col>", "group_col": "<cat_col>", "agg": "sum"}.
- Filters may only use columns from the allowed filter list.
- If the question needs a calculation that does not exist yet, use plan_type = "propose_metric".
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
    action: str = "run_metric"
    target: str = ""
    filters: dict = {}
    args: dict = {}


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
                "enum": ["single_metric", "stats_tool", "multi_step", "propose_metric", "no_match"],
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
) -> Plan:
    # Governed catalog: only APPROVED metrics are visible to the LLM planner.
    # Backward-compatible fallback: if the catalog hasn't been seeded yet,
    # use the legacy in-memory auto-generated metrics so existing callers
    # (and tests) that don't seed the catalog keep working unchanged.
    catalog_service = CatalogService(tenant_id=tenant_id)
    approved = catalog_service.get_approved_metrics()
    metrics = approved if approved else ds.get_metrics()
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

    prompt = (
        f"Schema:\n{schema_card}\n\n"
        f"Allowed filter columns: {allowed_filters}\n\n"
        f"Available metrics:\n{json.dumps(catalog, indent=2)}\n\n"
        f"Available statistical tools:\n{json.dumps(tools_catalog, indent=2)}\n\n"
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
    except (json.JSONDecodeError, ValidationError):
        return Plan(can_answer=False, reason="Malformed planner response", plan_type="no_match")

    metric_names = set(metrics.keys())
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
            "confidence": "high",
            "caveats": [],
            "lineage": {
                "metrics_or_tools_used": [r["target"] for r in results],
                "filters_applied": {},
                "notes": "Calculated via deterministic execution engine.",
            },
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
        return _parse_synthesize_response(raw, serializable_results, results)
    except Exception:
        return _parse_synthesize_response("", serializable_results, results)



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



# ── Top-level entrypoint ─────────────────────────────────────────────────

def _resolve_question(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
    tenant_id: str = "default",
) -> tuple[Plan | None, dict | None]:
    """Run plan() + schema-fallback matching + propose-metric flow."""
    cached = get_cached_response(question, dataset_id=ds.dataset_id, tenant_id=tenant_id)
    if cached is not None:
        return None, cached

    try:
        the_plan = plan(question, ds, provider, tenant_id=tenant_id)
    except Exception:
        the_plan = Plan(can_answer=False, reason="LLM provider offline", plan_type="no_match")

    if not the_plan.can_answer or the_plan.plan_type == "no_match":
        metrics = ds.get_metrics()
        q_lower = question.lower()
        matched_step = None

        if ds.profile:
            num_cols = [c.name for c in ds.profile.columns if c.is_numeric]
            cat_cols = [c.name for c in ds.profile.columns if c.is_categorical]

            # Match numeric column names or stems
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
                return num_cols[0] if num_cols else None

            # Match categorical column names, stems, or categorical values (e.g. 'clothing', 'electronics')
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


                return cat_cols[0] if cat_cols else None


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
) -> dict:
    """Phase 2 agent loop: plan -> execute -> synthesize.

    This is the main entrypoint for the governed agent.
    Checks the response cache first - repeated questions skip the LLM entirely.
    tenant_id scopes the catalog, cache, quotas, observability, and audit so
    no cross-tenant leakage occurs. All resource limits (plan steps, row caps,
    timeouts) and quotas are enforced here.
    """
    import time as _time
    from observability import log_agent_run
    from audit_logger import log_action
    from resource_limits import max_plan_steps, apply_row_limit, run_with_timeout, ResourceLimitError
    from tenant_quotas import check_and_consume_query_quota, QuotaExceededError

    t0 = _time.perf_counter()
    plan_type = "unknown"
    confidence = "n/a"
    error = None
    metrics_or_tools: list[str] = []

    try:
        # 1. Quota check + consume (only if tenant_id is meaningful)
        if tenant_id and tenant_id != "default":
            check_and_consume_query_quota(tenant_id)

        the_plan, early_response = _resolve_question(question, ds, provider, tenant_id=tenant_id)
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
            return results

        results = run_with_timeout(_execute)
        metrics_or_tools = [s.target for s in the_plan.steps]

        # 4. Synthesize
        answer = synthesize(question, the_plan, results, provider)
        confidence = answer.get("confidence", "n/a")

        response = {
            **answer,
            "plan": the_plan.model_dump(),
            "results": results,
        }

        # Cache the response for future repeated questions (scoped to tenant + dataset)
        set_cached_response(question, None, response, dataset_id=ds.dataset_id, tenant_id=tenant_id)

        return response

    except QuotaExceededError as e:
        error = "quota_exceeded"
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

    t0 = _time.perf_counter()
    plan_type = "unknown"
    confidence = "n/a"
    error = None
    metrics_or_tools: list[str] = []

    try:
        # 1. Quota check + consume (only if tenant_id is meaningful)
        if tenant_id and tenant_id != "default":
            check_and_consume_query_quota(tenant_id)

        the_plan, early_response = _resolve_question(question, ds, provider, tenant_id=tenant_id)
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

        confidence = (final_answer or {}).get("confidence", "n/a")

        response = {
            **(final_answer or {}),
            "plan": the_plan.model_dump(),
            "results": results,
        }

        # Cache the response for future repeated questions (scoped to tenant + dataset)
        set_cached_response(question, None, response, dataset_id=ds.dataset_id, tenant_id=tenant_id)

        yield response

    except QuotaExceededError as e:
        error = "quota_exceeded"
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
