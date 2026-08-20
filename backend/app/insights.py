"""Proactive insight generation.

Runs a fixed, hardcoded set of deterministic checks against an already-loaded,
already-profiled dataset, surfacing a short "things worth knowing" summary
BEFORE any question is asked. Every insight comes from an existing allowlisted
tool (stats_tools / agent_core.run_metric) — no free-form LLM analysis of raw
data, no new computation logic.

Each check is wrapped in try/except so a single tool failure never prevents
the others from running. Results are capped at MAX_INSIGHTS, prioritizing
notices (outliers, missingness) over info.
"""
from __future__ import annotations

from typing import Any

import agent_core
import pandas as pd
import stats_tools

MAX_INSIGHTS = 4
NULL_THRESHOLD = 0.05
CORR_THRESHOLD = 0.5
MAX_NUMERIC_FOR_CORR = 8


def generate_insights(ds: Any, catalog_service: Any = None) -> list[dict]:
    """Return a list of proactive insight dicts (max MAX_INSIGHTS).

    Each insight: {type, title, detail, severity, step} where `step` is a raw
    step dict in the same shape as agent result entries, so
    chart_builder.build_chart_spec() can run on it.
    """
    profile = getattr(ds, "profile", None)
    if profile is None:
        return []

    n_rows = getattr(profile, "n_rows", 0) or 0
    columns = list(getattr(profile, "columns", []) or [])
    numeric_cols = [c.name for c in columns if getattr(c, "is_numeric", False)]
    categorical_cols = [c.name for c in columns if getattr(c, "is_categorical", False)]
    temporal_cols = [c.name for c in columns if getattr(c, "is_temporal", False)]

    candidates: list[dict] = []

    # a) Outlier check on the first numeric column (reuse anomaly_detect).
    if numeric_cols:
        try:
            result = stats_tools.run_stats_tool(
                ds, "anomaly_detect", {"value_col": numeric_cols[0], "threshold": 2.0}
            )
            if _has_outliers(result):
                candidates.append({
                    "type": "outlier",
                    "title": f"Outliers found in {numeric_cols[0]}",
                    "detail": _summarize_outliers(result),
                    "severity": "notice",
                    "step": {"action": "run_stats", "target": "anomaly_detect", "result": result},
                })
        except Exception:
            pass

    # b) Trend check IF a date/datetime column exists (reuse trend tool).
    if temporal_cols and numeric_cols:
        try:
            result = stats_tools.run_stats_tool(
                ds,
                "trend",
                {"date_col": temporal_cols[0], "value_col": numeric_cols[0], "freq": "D"},
            )
            if result is not None and len(result) > 0:
                # Chartable shape for build_chart_spec: list of {period, value}.
                candidates.append({
                    "type": "trend",
                    "title": f"{numeric_cols[0]} trend over {temporal_cols[0]}",
                    "detail": "See chart for movement over time.",
                    "severity": "info",
                    "step": {
                        "action": "run_stats",
                        "target": "trend",
                        "result": result.to_dict(orient="records"),
                    },
                })
        except Exception:
            pass

    # c) Top breakdown: run the approved (or auto) breakdown metric for the
    #    first categorical column — never invent a new metric.
    if categorical_cols:
        try:
            metric_catalog = _get_metric_catalog(ds, catalog_service)
            match = _find_breakdown_metric(metric_catalog, categorical_cols[0])
            if match:
                m = {k: metric_catalog[match][k] for k in ("column", "agg", "groupby", "base_filters") if k in metric_catalog[match]}
                result = agent_core.run_metric(ds, m, {})
                if isinstance(result, pd.Series) and len(result) > 0:
                    result_dict = result.to_dict()
                    candidates.append({
                        "type": "breakdown",
                        "title": f"Breakdown by {categorical_cols[0]}",
                        "detail": _summarize_breakdown(result_dict),
                        "severity": "info",
                        "step": {"action": "run_metric", "target": match, "groupby": categorical_cols[0], "result": result_dict},
                    })
        except Exception:
            pass

    # d) Missingness: flag any column with >5% nulls.
    if n_rows:
        for col in columns:
            null_ratio = (getattr(col, "n_null", 0) or 0) / n_rows
            if null_ratio > NULL_THRESHOLD:
                candidates.append({
                    "type": "missingness",
                    "title": f"{col.name} has missing values",
                    "detail": f"{null_ratio * 100:.1f}% of rows are missing {col.name}.",
                    "severity": "notice",
                    "step": {},
                })

    # e) Strongest correlation pair IF 2+ numeric columns exist (reuse
    #    correlation tool per pair). Only surfaced when |r| > 0.5.
    if len(numeric_cols) >= 2:
        try:
            matrix, pair = _strongest_pair(ds, numeric_cols[:MAX_NUMERIC_FOR_CORR])
            if pair is not None and abs(pair[2]) > CORR_THRESHOLD:
                candidates.append({
                    "type": "correlation",
                    "title": f"{pair[0]} and {pair[1]} are correlated",
                    "detail": f"Correlation of {pair[2]:.2f}.",
                    "severity": "info",
                    "step": {"action": "run_stats", "target": "correlation_matrix", "result": matrix},
                })
        except Exception:
            pass

    # Prioritize notices (outliers, missingness) over info, cap at MAX_INSIGHTS.
    candidates.sort(key=lambda c: 0 if c["severity"] == "notice" else 1)
    return candidates[:MAX_INSIGHTS]


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_metric_catalog(ds: Any, catalog_service: Any) -> dict:
    """Approved catalog if present, else the auto-generated in-memory metrics
    (same backward-compatible fallback pattern as agent_phase2.plan())."""
    if catalog_service is not None:
        approved = catalog_service.get_approved_metrics()
        if approved:
            return approved
    return ds.get_metrics()


def _find_breakdown_metric(metric_catalog: dict, category_col: str) -> str | None:
    for name, m in metric_catalog.items():
        if isinstance(m, dict) and m.get("groupby") == category_col:
            return name
    return None


def _has_outliers(result: Any) -> bool:
    if isinstance(result, pd.DataFrame):
        return len(result) > 0
    if isinstance(result, list):
        return len(result) > 0
    if isinstance(result, dict):
        return bool(result.get("outliers"))
    return False


def _summarize_outliers(result: Any) -> str:
    if isinstance(result, pd.DataFrame):
        count = len(result)
    elif isinstance(result, list):
        count = len(result)
    else:
        count = len(result.get("outliers", [])) if isinstance(result, dict) else 0
    return f"{count} statistical outlier(s) detected."


def _summarize_breakdown(result: dict) -> str:
    if not result:
        return "No breakdown data."
    top = max(result.items(), key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 0)
    return f"{top[0]} leads at {top[1]:,.2f}."


def _strongest_pair(ds: Any, numeric_cols: list[str]) -> tuple[dict, tuple | None]:
    """Compute the correlation matrix (dict[row][col] = r) for the given
    numeric columns and return (matrix, (col_a, col_b, r)) for the strongest pair."""
    matrix: dict[str, dict] = {}
    best: tuple | None = None
    for i in range(len(numeric_cols)):
        matrix[numeric_cols[i]] = {}
        for j in range(len(numeric_cols)):
            if i == j:
                matrix[numeric_cols[i]][numeric_cols[j]] = 1.0
                continue
            val = stats_tools.run_stats_tool(
                ds, "correlation", {"col_a": numeric_cols[i], "col_b": numeric_cols[j]}
            )
            val = float(val or 0)
            matrix[numeric_cols[i]][numeric_cols[j]] = val
            if best is None or abs(val) > abs(best[2]):
                best = (numeric_cols[i], numeric_cols[j], val)
    return matrix, best