"""
Governed Model Tools — Phase 2.

Safety invariant (same as metrics):
  The LLM never generates training or inference code.
  It only selects an approved model tool name + arguments.
  Execution is deterministic and fully controlled by us.
"""

from __future__ import annotations

from typing import Any
from datetime import datetime

import pandas as pd
import numpy as np
from pydantic import BaseModel, Field

from data_source import DataSource


# ──────────────────────────────────────────────────────────────
# 1. Model Tool Interface
# ──────────────────────────────────────────────────────────────

class ModelToolSpec(BaseModel):
    """Metadata that the planner (and admin UI) sees."""
    name: str
    description: str
    synonyms: list[str] = []
    args_schema: dict[str, str] = {}          # human-readable
    requires_approval: bool = True
    risk: str = "medium"                      # low | medium | high
    version: str = "1.0.0"


class ModelToolResult(BaseModel):
    """Standard result shape returned to the synthesizer."""
    tool_name: str
    success: bool
    summary: str
    data: Any = None                          # JSON-serializable
    metrics: dict[str, float] = {}            # e.g. mape, rmse
    lineage: dict[str, Any] = {}
    caveats: list[str] = []


# ──────────────────────────────────────────────────────────────
# 2. Registry of available model tools (code-level)
# ──────────────────────────────────────────────────────────────

MODEL_TOOL_SPECS: dict[str, ModelToolSpec] = {
    "forecast": ModelToolSpec(
        name="forecast",
        description="Time-series forecast of a numeric column using exponential smoothing / simple trend.",
        synonyms=[
            "forecast", "predict future", "future sales", "next months",
            "projection", "what will sales be", "forecast revenue",
            "predict next period", "time series forecast",
        ],
        args_schema={
            "value_col": "numeric column to forecast",
            "date_col": "date column",
            "periods": "number of future periods (default 3)",
            "freq": "M (month), W (week), or D (day)",
        },
        risk="medium",
        version="1.0.0",
    ),
    # Future tools can be added here:
    # "anomaly_model", "clustering", "regression", ...
}


VALID_MODEL_TOOL_NAMES = set(MODEL_TOOL_SPECS.keys())


# ──────────────────────────────────────────────────────────────
# 3. First concrete tool: Forecasting
# ──────────────────────────────────────────────────────────────

def _prepare_ts(ds: DataSource, date_col: str, value_col: str, freq: str = "M") -> pd.Series:
    """Aggregate to a regular time series."""
    freq_map = {"M": "MS", "W": "W-MON", "D": "D"}
    pandas_freq = freq_map.get(freq, "MS")

    df = ds.query(
        f"""
        SELECT
            date_trunc('{ {"M":"month","W":"week","D":"day"}[freq] }', CAST("{date_col}" AS DATE)) AS period,
            SUM("{value_col}") AS value
        FROM {ds.table_name}
        WHERE "{date_col}" IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """
    )
    if df.empty:
        raise ValueError("No data available for forecasting")

    df["period"] = pd.to_datetime(df["period"])
    ts = df.set_index("period")["value"].asfreq(pandas_freq, fill_value=0.0)
    return ts


def run_forecast(
    ds: DataSource,
    value_col: str,
    date_col: str,
    periods: int = 3,
    freq: str = "M",
) -> ModelToolResult:
    """
    Simple, robust forecasting using Holt's linear trend (exponential smoothing).
    No external heavy dependencies required beyond pandas/numpy.
    """
    from data_source import DataSource  # already imported

    # Validation
    if value_col not in [c.name for c in ds.profile.columns]:
        raise ValueError(f"Column '{value_col}' not found")
    if date_col not in [c.name for c in ds.profile.columns]:
        raise ValueError(f"Column '{date_col}' not found")

    periods = max(1, min(int(periods), 12))  # safety cap
    freq = freq if freq in ("M", "W", "D") else "M"

    ts = _prepare_ts(ds, date_col, value_col, freq)

    if len(ts) < 4:
        return ModelToolResult(
            tool_name="forecast",
            success=False,
            summary="Not enough historical points for a reliable forecast (need ≥ 4).",
            caveats=["Insufficient history"],
            lineage={"value_col": value_col, "date_col": date_col, "n_history": len(ts)},
        )

    # ----- Holt's linear trend (simple & dependency-free) -----
    # Level + Trend exponential smoothing
    alpha = 0.4   # level smoothing
    beta = 0.3    # trend smoothing

    level = float(ts.iloc[0])
    trend = float(ts.iloc[1] - ts.iloc[0]) if len(ts) > 1 else 0.0

    fitted = []
    for x in ts:
        prev_level = level
        level = alpha * x + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
        fitted.append(level + trend)

    # Forecast future
    last_level = level
    last_trend = trend
    forecasts = []
    for h in range(1, periods + 1):
        forecasts.append(last_level + h * last_trend)

    # Build result frame
    last_date = ts.index[-1]
    if freq == "M":
        future_idx = pd.date_range(last_date + pd.offsets.MonthBegin(1), periods=periods, freq="MS")
    elif freq == "W":
        future_idx = pd.date_range(last_date + pd.Timedelta(weeks=1), periods=periods, freq="W-MON")
    else:
        future_idx = pd.date_range(last_date + pd.Timedelta(days=1), periods=periods, freq="D")

    forecast_df = pd.DataFrame({
        "period": future_idx.astype(str),
        "forecast": [round(float(v), 2) for v in forecasts],
    })

    # Simple in-sample error (MAPE on last 3 points if possible)
    mape = None
    if len(ts) >= 3:
        actual = ts.iloc[-3:].values
        pred = np.array(fitted[-3:])
        mape = float(np.mean(np.abs((actual - pred) / np.maximum(actual, 1e-6))) * 100)

    return ModelToolResult(
        tool_name="forecast",
        success=True,
        summary=f"Forecast of {value_col} for next {periods} period(s) using Holt linear trend.",
        data=forecast_df.to_dict(orient="records"),
        metrics={"mape_last3": round(mape, 2) if mape is not None else None},
        lineage={
            "value_col": value_col,
            "date_col": date_col,
            "freq": freq,
            "periods": periods,
            "n_history": len(ts),
            "method": "holt_linear_trend",
            "alpha": alpha,
            "beta": beta,
        },
        caveats=[
            "Simple exponential smoothing — not suitable for strong seasonality or very noisy series.",
            "Always review forecasts with domain experts before decisions.",
        ],
    )


# ──────────────────────────────────────────────────────────────
# 4. Dispatcher
# ──────────────────────────────────────────────────────────────

def run_model_tool(ds: DataSource, tool_name: str, args: dict) -> ModelToolResult:
    """Only approved tools can be executed."""
    if tool_name not in VALID_MODEL_TOOL_NAMES:
        return ModelToolResult(
            tool_name=tool_name,
            success=False,
            summary=f"Model tool '{tool_name}' is not registered or not approved.",
            caveats=["Unknown or unapproved model tool"],
        )

    if tool_name == "forecast":
        return run_forecast(
            ds,
            value_col=args.get("value_col", "sales"),
            date_col=args.get("date_col", "date"),
            periods=int(args.get("periods", 3)),
            freq=args.get("freq", "M"),
        )

    return ModelToolResult(
        tool_name=tool_name,
        success=False,
        summary="Tool registered but not implemented yet.",
    )


def get_model_tools_for_llm() -> list[dict]:
    """What the planner sees (only approved tools)."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "synonyms": spec.synonyms,
            "args": spec.args_schema,
        }
        for spec in MODEL_TOOL_SPECS.values()
    ]
