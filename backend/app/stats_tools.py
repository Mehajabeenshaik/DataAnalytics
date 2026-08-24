"""
Phase 2 Statistical Tools — deterministic, column-validated, no LLM involvement.

Each tool:
  1. Validates column names against the DataSource profile.
  2. Executes a deterministic DuckDB query.
  3. Returns pure data (DataFrame, Series, float, or dict).

The LLM never writes SQL — it only picks a tool name and supplies arguments.
All column validation happens here, so an LLM cannot inject arbitrary column
names or expressions.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_source import DataSource


# ── Tool catalog (for the LLM planner prompt) ─────────────────────────────

ALLOWED_STATS_TOOLS: list[dict] = [
    {
        "name": "describe",
        "description": "Summary statistics: count, mean, std, min, max, nulls for each column.",
        "synonyms": [
            "summary statistics",
            "describe the data",
            "summarize",
            "summarise",
            "describe",
            "statistics",
            "overview of the data",
            "data summary",
        ],
        "args": {"columns": "list of column names"},
    },
    {
        "name": "value_counts",
        "description": "Frequency table of a categorical column.",
        "synonyms": [
            "value counts",
            "distribution of",
            "how many of each",
            "breakdown of values",
            "count of each value",
            "frequency of values",
            "frequency table",
        ],
        "args": {"column": "column name", "top_n": "int, default 10"},
    },
    {
        "name": "correlation",
        "description": "Pearson correlation between two numeric columns.",
        "args": {"col_a": "numeric column name", "col_b": "numeric column name"},
    },
    {
        "name": "group_compare",
        "description": "Sum, mean, max, or min of a numeric column grouped by a categorical column.",
        "args": {
            "value_col": "numeric column name",
            "group_col": "categorical column name",
            "agg": '"sum", "mean", "max", or "min"',
            "date_col": "optional date column to filter by calendar month",
            "month": "optional int 1-12; when set with date_col, only that month is included",
        },
    },
    {
        "name": "missingness",
        "description": "Null percentage per column.",
        "args": {"columns": "optional list of column names"},
    },
    {
        "name": "trend",
        "description": "Time aggregation of a numeric column by date period.",
        "synonyms": [
            "time series",
            "trend over time",
            "values over time",
            "historical trend",
            "time progression",
            "trend",
        ],
        "args": {
            "date_col": "date/time column name",
            "value_col": "numeric column name",
            "freq": '"M" (month), "W" (week), or "D" (day)',
        },
    },
    {
        "name": "anomaly_detect",
        "description": "Identify statistical outliers or anomalies in a numeric column using Z-score.",
        "synonyms": ["outliers", "anomalies", "unusual values", "extreme values", "anomaly detection"],
        "args": {"value_col": "numeric column name", "threshold": "float Z-score threshold, default 2.0"},
    },
    {
        "name": "filtered_agg",
        "description": "Aggregate (sum/mean/count/max/min) of a numeric column over rows filtered by a month on a date column.",
        "synonyms": ["total in a month", "sales for january", "monthly total"],
        "args": {
            "value_col": "numeric column name",
            "agg": '"sum", "mean", "count", "max", or "min"',
            "date_col": "date/time column name to filter on",
            "month": "int 1-12",
        },
    },
]


VALID_TOOL_NAMES = {t["name"] for t in ALLOWED_STATS_TOOLS}


# ── Helpers ───────────────────────────────────────────────────────────────

def _validate_column(ds: DataSource, col: str) -> str:
    """Return the column name if it exists in the profile, else raise ValueError."""
    if not ds.profile:
        raise RuntimeError("DataSource has no profile. Load data first.")
    names = {c.name for c in ds.profile.columns}
    if col not in names:
        raise ValueError(
            f"Column '{col}' not found in data. Available: {sorted(names)}"
        )
    return col


def _is_numeric(ds: DataSource, col: str) -> bool:
    for c in ds.profile.columns:
        if c.name == col:
            return c.is_numeric
    return False


def _is_temporal(ds: DataSource, col: str) -> bool:
    for c in ds.profile.columns:
        if c.name == col:
            return c.is_temporal
    return False


# ── Tool implementations ──────────────────────────────────────────────────


def describe(ds: DataSource, columns: list[str] | None = None) -> pd.DataFrame:
    """Count, mean, std, min, max, nulls for each column.

    For numeric columns: full stats.
    For non-numeric columns: count, n_unique, nulls only.
    """
    if not ds.profile:
        raise RuntimeError("DataSource has no profile. Load data first.")

    all_cols = [c.name for c in ds.profile.columns]
    if columns is None:
        columns = all_cols
    else:
        for c in columns:
            _validate_column(ds, c)

    rows = []
    for col in columns:
        is_num = _is_numeric(ds, col)
        if is_num:
            df = ds.query(
                f"""
                SELECT
                    COUNT("{col}") AS count,
                    AVG("{col}") AS mean,
                    STDDEV_SAMP("{col}") AS std,
                    MIN("{col}") AS min,
                    MAX("{col}") AS max,
                    COUNT(*) - COUNT("{col}") AS nulls
                FROM {ds.table_name}
                """
            )
            row = df.iloc[0].to_dict()
            row["column"] = col
            row["dtype"] = "numeric"
        else:
            df = ds.query(
                f"""
                SELECT
                    COUNT("{col}") AS count,
                    COUNT(DISTINCT "{col}") AS n_unique,
                    COUNT(*) - COUNT("{col}") AS nulls
                FROM {ds.table_name}
                """
            )
            row = df.iloc[0].to_dict()
            row["column"] = col
            row["dtype"] = "categorical"
            row["mean"] = None
            row["std"] = None
            row["min"] = None
            row["max"] = None
        rows.append(row)

    result = pd.DataFrame(rows)
    # Reorder columns for readability
    ordered = ["column", "dtype", "count", "mean", "std", "min", "max", "nulls", "n_unique"]
    ordered = [c for c in ordered if c in result.columns]
    return result[ordered]


def value_counts(ds: DataSource, column: str, top_n: int = 10) -> pd.DataFrame:
    """Frequency table of a categorical column, top N values."""
    _validate_column(ds, column)
    if top_n < 1:
        top_n = 10

    df = ds.query(
        f"""
        SELECT "{column}" AS value, COUNT(*) AS count
        FROM {ds.table_name}
        GROUP BY 1
        ORDER BY count DESC
        LIMIT {int(top_n)}
        """
    )
    total = ds.query(f"SELECT COUNT(*) AS n FROM {ds.table_name}").iloc[0, 0]
    df["pct"] = (df["count"] / total * 100).round(2) if total else 0.0
    return df


def correlation(ds: DataSource, col_a: str, col_b: str) -> float:
    """Pearson correlation between two numeric columns."""
    _validate_column(ds, col_a)
    _validate_column(ds, col_b)
    if not _is_numeric(ds, col_a):
        raise ValueError(f"'{col_a}' is not numeric. Correlation requires two numeric columns.")
    if not _is_numeric(ds, col_b):
        raise ValueError(f"'{col_b}' is not numeric. Correlation requires two numeric columns.")

    df = ds.query(
        f'SELECT CORR("{col_a}", "{col_b}") AS corr FROM {ds.table_name}'
    )
    val = df.iloc[0, 0]
    return float(val) if val is not None else 0.0


def _month_where(ds: DataSource, date_col: str | None, month: int | None) -> tuple[str, list]:
    """SQL fragment + params that restrict rows to a calendar month.

    Returns ("", []) when no month filter is requested. Raises if a month
    is requested but the date column is missing — callers must not silently
    drop the filter.
    """
    if date_col is None or month is None:
        return "", []
    _validate_column(ds, date_col)
    return (
        f'WHERE "{date_col}" IS NOT NULL '
        f'AND EXTRACT(MONTH FROM CAST("{date_col}" AS DATE)) = ?',
        [int(month)],
    )


def group_compare(
    ds: DataSource,
    value_col: str,
    group_col: str,
    agg: str = "sum",
    date_col: str | None = None,
    month: int | None = None,
) -> pd.Series:
    """Sum or mean of a numeric column grouped by a categorical column."""
    _validate_column(ds, value_col)
    _validate_column(ds, group_col)
    if not _is_numeric(ds, value_col):
        raise ValueError(f"'{value_col}' is not numeric. group_compare requires a numeric value column.")

    agg_lower = agg.lower()
    if agg_lower not in ("sum", "mean", "max", "min"):
        raise ValueError(f"agg must be 'sum', 'mean', 'max', or 'min', got '{agg}'")

    sql_agg = {
        "sum": "SUM",
        "mean": "AVG",
        "max": "MAX",
        "min": "MIN",
    }[agg_lower]
    where_sql, params = _month_where(ds, date_col, month)
    df = ds.query(
        f"""
        SELECT "{group_col}" AS key, {sql_agg}("{value_col}") AS value
        FROM {ds.table_name}
        {where_sql}
        GROUP BY 1
        ORDER BY value DESC
        """,
        params,
    )
    return df.set_index("key")["value"]


def missingness(ds: DataSource, columns: list[str] | None = None) -> pd.DataFrame:
    """Null percentage per column."""
    if not ds.profile:
        raise RuntimeError("DataSource has no profile. Load data first.")

    all_cols = [c.name for c in ds.profile.columns]
    if columns is None:
        columns = all_cols
    else:
        for c in columns:
            _validate_column(ds, c)

    rows = []
    for col in columns:
        df = ds.query(
            f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) - COUNT("{col}") AS nulls
            FROM {ds.table_name}
            """
        )
        total = int(df.iloc[0, 0])
        nulls = int(df.iloc[0, 1])
        pct = round(nulls / total * 100, 2) if total else 0.0
        rows.append({"column": col, "total": total, "nulls": nulls, "null_pct": pct})

    return pd.DataFrame(rows)


def trend(
    ds: DataSource,
    date_col: str,
    value_col: str,
    freq: str = "M",
) -> pd.DataFrame:
    """Time aggregation of a numeric column by date period.

    freq: 'M' (month), 'W' (week), or 'D' (day).
    """
    _validate_column(ds, date_col)
    _validate_column(ds, value_col)
    if not _is_numeric(ds, value_col):
        raise ValueError(f"'{value_col}' is not numeric. trend requires a numeric value column.")

    freq_map = {"M": "month", "W": "week", "D": "day"}
    if freq not in freq_map:
        raise ValueError(f"freq must be one of {list(freq_map.keys())}, got '{freq}'")

    # DuckDB date_trunc accepts 'month', 'week', 'day'
    trunc = freq_map[freq]
    df = ds.query(
        f"""
        SELECT
            date_trunc('{trunc}', CAST("{date_col}" AS DATE)) AS period,
            SUM("{value_col}") AS value,
            COUNT(*) AS n
        FROM {ds.table_name}
        WHERE "{date_col}" IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """
    )
    return df


def filtered_agg(
    ds: DataSource,
    value_col: str,
    agg: str = "sum",
    date_col: str | None = None,
    month: int | None = None,
) -> float | int:
    """Aggregate a numeric column over rows filtered by calendar month.

    If date_col and month are provided, only rows whose date falls in that
    calendar month are included. If the filter cannot be applied (missing
    date column or unparseable dates), raises ValueError so the caller can
    refuse rather than silently return an UNFILTERED total.
    """
    _validate_column(ds, value_col)
    if not _is_numeric(ds, value_col):
        raise ValueError(f"'{value_col}' is not numeric. filtered_agg requires a numeric value column.")

    agg_lower = (agg or "sum").lower()
    if agg_lower not in ("sum", "mean", "count", "max", "min"):
        raise ValueError(f"agg must be 'sum', 'mean', 'count', 'max', or 'min', got '{agg}'")

    where_sql, params = _month_where(ds, date_col, month)

    sql_agg = {"sum": "SUM", "mean": "AVG", "count": "COUNT", "max": "MAX", "min": "MIN"}[agg_lower]
    df = ds.query(
        f'SELECT {sql_agg}("{value_col}") AS v FROM {ds.table_name} {where_sql}',
        params,
    )
    val = df.iloc[0, 0]
    if val is None or pd.isna(val):
        # Month filter matched zero rows — surface as error, never a fake 0.
        # (DuckDB NULL arrives via fetchdf() as NaN, not Python None.)
        raise ValueError(f"No rows found for month {month} on '{date_col}'")
    if agg_lower == "count":
        return int(val)
    return float(val)


def anomaly_detect(ds: DataSource, value_col: str, threshold: float = 2.0) -> pd.DataFrame:
    """Identify statistical outliers/anomalies in a numeric column via Z-score."""
    _validate_column(ds, value_col)
    if not _is_numeric(ds, value_col):
        raise ValueError(f"'{value_col}' is not numeric.")

    df = ds.query(
        f"""
        WITH stats AS (
            SELECT AVG("{value_col}") as mean_val, STDDEV("{value_col}") as std_val
            FROM {ds.table_name}
        )
        SELECT *, ROUND(("{value_col}" - stats.mean_val) / NULLIF(stats.std_val, 0), 2) as z_score
        FROM {ds.table_name}, stats
        WHERE ABS(("{value_col}" - stats.mean_val) / NULLIF(stats.std_val, 0)) >= {threshold}
        ORDER BY ABS(z_score) DESC
        LIMIT 20
        """
    )
    return df


# ── Dispatcher ────────────────────────────────────────────────────────────

def run_stats_tool(ds: DataSource, tool_name: str, args: dict) -> Any:
    """Dispatch to the named stats tool. Validates tool name and column args.

    This is the ONLY entry point for executing stats tools — the LLM never
    calls the individual functions directly.
    """
    if tool_name not in VALID_TOOL_NAMES:
        raise ValueError(
            f"Unknown stats tool '{tool_name}'. Allowed: {sorted(VALID_TOOL_NAMES)}"
        )

    if tool_name == "describe":
        return describe(ds, args.get("columns"))
    elif tool_name == "value_counts":
        return value_counts(ds, args["column"], args.get("top_n", 10))
    elif tool_name == "correlation":
        return correlation(ds, args["col_a"], args["col_b"])
    elif tool_name == "group_compare":
        return group_compare(
            ds,
            args["value_col"],
            args["group_col"],
            args.get("agg", "sum"),
            args.get("date_col"),
            args.get("month"),
        )
    elif tool_name == "missingness":
        return missingness(ds, args.get("columns"))
    elif tool_name == "trend":
        return trend(ds, args["date_col"], args["value_col"], args.get("freq", "M"))
    elif tool_name == "anomaly_detect":
        return anomaly_detect(ds, args["value_col"], args.get("threshold", 2.0))
    elif tool_name == "filtered_agg":
        return filtered_agg(
            ds,
            args["value_col"],
            args.get("agg", "sum"),
            args.get("date_col"),
            args.get("month"),
        )
    else:
        raise ValueError(f"Tool '{tool_name}' not implemented.")
