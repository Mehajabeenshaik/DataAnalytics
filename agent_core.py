"""
Phase 1 governed agent — data-agnostic, still fully safe.
LLM only selects from the auto-generated metric catalog.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from pydantic import BaseModel, ValidationError

from data_source import DataSource
from metric_factory import generate_metrics, get_metric_catalog_for_llm
from llm_provider import LLMProvider


# ── Prompts (elite, tight, low-hallucination) ────────────────────────────

METRIC_ROUTER_SYSTEM = """You are a precise metric router for a local data analyst agent.
Your ONLY job is to choose exactly one metric from the provided catalog that best answers the user question, plus optional filters.

Rules (strict):
- Choose ONLY from the given metric names. Never invent a metric.
- Filters may only use columns from the allowed filter list.
- If no metric genuinely answers the question, return {"no_match": true}.
- Prefer the most specific metric when several could work.
- Output ONLY valid JSON, nothing else.

Output schema:
{
  "metric_name": "<name or null>",
  "filters": {"<column>": "<value>"},
  "no_match": false
}
"""

EXPLAIN_SYSTEM = """You are a senior data analyst explaining results to a business user.
Be precise, concise, and honest. Never invent numbers.
Respond ONLY with valid JSON:
{
  "answer": "plain English explanation of the result",
  "confidence": "high" | "low",
  "caveat": "string or null"
}
Set confidence to "low" when the result set is small, the question implies causation the data cannot prove, or important filters are missing.
"""


# ── Step 1: metric selection (LLM call #1) ───────────────────────────────

class MetricSelection(BaseModel):
    metric_name: str | None = None
    filters: dict = {}
    no_match: bool = False


def select_metric(
    question: str,
    metrics: dict,
    allowed_filters: list[str],
    provider: LLMProvider,
) -> MetricSelection:
    catalog = get_metric_catalog_for_llm(metrics)
    schema_hint = f"Allowed filter columns: {allowed_filters}"

    prompt = (
        f"{schema_hint}\n\n"
        f"Available metrics:\n{json.dumps(catalog, indent=2)}\n\n"
        f"Question: {question}"
    )

    raw = provider.generate(prompt, system_prompt=METRIC_ROUTER_SYSTEM, temperature=0.05)

    try:
        data = json.loads(raw)
        # Force safety: reject any metric name not in the catalog
        if data.get("metric_name") not in metrics:
            data["metric_name"] = None
            data["no_match"] = True
        # Strip any filter keys outside the allowlist
        data["filters"] = {
            k: v
            for k, v in data.get("filters", {}).items()
            if k in allowed_filters
        }
        return MetricSelection(**data)
    except (json.JSONDecodeError, ValidationError):
        return MetricSelection(no_match=True)


# ── Step 2: deterministic query execution (NO LLM call) ──────────────────

def run_metric(ds: DataSource, metric: dict, filters: dict) -> Any:
    """Deterministic execution — zero LLM involvement."""
    table = ds.table_name
    col = metric["column"]
    agg = metric["agg"]
    groupby = metric.get("groupby")
    base = metric.get("base_filters", {})

    # Merge filters (user filters override base)
    all_filters = {**base, **filters}

    where_parts: list[str] = []
    params: list = []
    for k, v in all_filters.items():
        where_parts.append(f'"{k}" = ?')
        params.append(v)
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    if agg == "sum":
        if groupby:
            sql = (
                f'SELECT "{groupby}" AS key, SUM("{col}") AS value '
                f"FROM {table}{where_sql} GROUP BY 1 ORDER BY value DESC"
            )
            return ds.query(sql, params).set_index("key")["value"]
        sql = f'SELECT SUM("{col}") FROM {table}{where_sql}'
        return float(ds.query(sql, params).iloc[0, 0] or 0)

    if agg == "mean":
        sql = f'SELECT AVG("{col}") FROM {table}{where_sql}'
        return float(ds.query(sql, params).iloc[0, 0] or 0)

    if agg == "count":
        sql = f"SELECT COUNT(*) FROM {table}{where_sql}"
        return int(ds.query(sql, params).iloc[0, 0])

    if agg == "nunique":
        sql = f'SELECT COUNT(DISTINCT "{col}") FROM {table}{where_sql}'
        return int(ds.query(sql, params).iloc[0, 0])

    raise ValueError(f"Unknown aggregation: {agg}")


# ── Step 3: explanation (LLM call #2) ─────────────────────────────────────

def explain(question: str, metric_name: str, result: Any, provider: LLMProvider) -> dict:
    is_small = hasattr(result, "__len__") and len(result) < 3

    prompt = f"Question: {question}\nMetric: {metric_name}\nResult:\n{result}"

    raw = provider.generate(prompt, system_prompt=EXPLAIN_SYSTEM, temperature=0.4)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "answer": str(result),
            "confidence": "low",
            "caveat": "Could not generate a clean explanation.",
        }

    if is_small and data.get("confidence") == "high":
        data["confidence"] = "low"
        data["caveat"] = (data.get("caveat") or "") + " Small result set — interpret with caution."

    return data


# ── Top-level entrypoint ──────────────────────────────────────────────────

def ask(question: str, ds: DataSource, provider: LLMProvider) -> dict:
    metrics = generate_metrics(ds)
    selection = select_metric(
        question, metrics, ds.allowed_filter_columns, provider
    )

    if selection.no_match or not selection.metric_name:
        return {
            "answer": "I don't have a reliable metric that answers this question with the current data.",
            "metric_used": None,
            "confidence": "n/a",
            "caveat": "No matching metric in the allowlist.",
            "filters_used": selection.filters,
            "result": None,
        }

    metric = metrics[selection.metric_name]
    result = run_metric(ds, metric, selection.filters)
    explanation = explain(question, selection.metric_name, result, provider)

    return {
        **explanation,
        "metric_used": selection.metric_name,
        "filters_used": selection.filters,
        "result": result,
    }