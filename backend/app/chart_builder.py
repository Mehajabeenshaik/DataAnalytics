"""Builds minimal Vega-Lite specs from already-computed, already-verified
agent results. No LLM involvement — pure data shaping."""
from __future__ import annotations

from typing import Any

MAX_POINTS = 50


def build_chart_spec(step: dict) -> dict | None:
    result = step.get("result")
    target = (step.get("target") or "").lower()

    if result is None:
        return None

    # Breakdown / groupby result: dict[str, number]
    if isinstance(result, dict) and _is_breakdown(result):
        return _bar_chart(result, target)

    # Time-series result: dict[str-date, number] or list of {date, value}
    if isinstance(result, dict) and _looks_like_dates(result):
        return _line_chart(result, target)

    if isinstance(result, list) and result and isinstance(result[0], dict):
        if _looks_like_series_records(result):
            return _line_chart_from_records(result, target)

    # Correlation matrix: dict[str, dict[str, number]]
    if isinstance(result, dict) and _is_matrix(result):
        return _heatmap(result, target)

    # Scalars, single numbers, plain text answers -> nothing to chart
    return None


def _is_breakdown(d: dict) -> bool:
    return bool(d) and all(isinstance(v, (int, float)) for v in d.values())


def _is_matrix(d: dict) -> bool:
    return bool(d) and all(isinstance(v, dict) for v in d.values())


def _looks_like_dates(d: dict) -> bool:
    keys = list(d.keys())
    return bool(keys) and all(_looks_date(k) for k in keys[:5])


def _looks_date(s: Any) -> bool:
    s = str(s)
    return len(s) >= 7 and s[4:5] == "-" or (len(s) == 10 and s[4] == "-" and s[7] == "-")


def _looks_like_series_records(records: list[dict]) -> bool:
    sample = records[0]
    keys = {k.lower() for k in sample.keys()}
    return bool(keys & {"date", "period", "month", "week"})


def _cap(items: list[tuple[str, float]]) -> tuple[list[tuple[str, float]], bool]:
    if len(items) <= MAX_POINTS:
        return items, False
    return items[:MAX_POINTS], True


def _bar_chart(result: dict, target: str) -> dict:
    items, truncated = _cap(list(result.items()))
    values = [{"category": str(k), "value": v} for k, v in items]
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"Breakdown for {target}" if target else "Breakdown",
        "mark": "bar",
        "data": {"values": values},
        "encoding": {
            "x": {"field": "category", "type": "nominal", "sort": "-y"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    if truncated:
        spec["_note"] = f"Truncated to top {MAX_POINTS} categories"
    return spec


def _line_chart(result: dict, target: str) -> dict:
    items, truncated = _cap(sorted(result.items()))
    values = [{"date": str(k), "value": v} for k, v in items]
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"Trend for {target}" if target else "Trend",
        "mark": "line",
        "data": {"values": values},
        "encoding": {
            "x": {"field": "date", "type": "temporal"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    if truncated:
        spec["_note"] = f"Truncated to first {MAX_POINTS} points"
    return spec


def _line_chart_from_records(records: list[dict], target: str) -> dict:
    date_key = next((k for k in records[0].keys() if k.lower() in ("date", "period", "month", "week")), None)
    value_key = next((k for k in records[0].keys() if k != date_key and isinstance(records[0][k], (int, float))), None)
    if not date_key or not value_key:
        return None  # type: ignore
    items = records[:MAX_POINTS]
    truncated = len(records) > MAX_POINTS
    values = [{"date": str(r[date_key]), "value": r[value_key]} for r in items]
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"Trend for {target}" if target else "Trend",
        "mark": "line",
        "data": {"values": values},
        "encoding": {
            "x": {"field": "date", "type": "temporal"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    if truncated:
        spec["_note"] = f"Truncated to first {MAX_POINTS} points"
    return spec


def _heatmap(result: dict, target: str) -> dict:
    values = []
    for row_key, row in result.items():
        for col_key, v in row.items():
            values.append({"row": str(row_key), "col": str(col_key), "value": v})
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"Correlation for {target}" if target else "Correlation matrix",
        "mark": "rect",
        "data": {"values": values},
        "encoding": {
            "x": {"field": "col", "type": "nominal"},
            "y": {"field": "row", "type": "nominal"},
            "color": {"field": "value", "type": "quantitative"},
        },
    }