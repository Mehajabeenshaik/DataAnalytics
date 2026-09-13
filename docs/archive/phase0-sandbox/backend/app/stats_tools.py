import pandas as pd
from typing import List, Dict, Any
from .data_source import DataSource

ALLOWED_STATS_TOOLS = {"describe", "trend", "correlation", "value_counts", "missing_stats"}
VALID_TOOL_NAMES = ALLOWED_STATS_TOOLS

def _ensure_column(ds: DataSource, column: str) -> None:
    if column not in ds.column_names:
        raise ValueError(f"Column '{column}' does not exist in the data source.")

def describe(ds: DataSource, column: str) -> Dict[str, Any]:
    """Return basic descriptive statistics for a numeric column."""
    _ensure_column(ds, column)
    df = ds.load_dataframe()
    desc = df[column].describe().to_dict()
    return {"column": column, "description": desc}

def trend(ds: DataSource, column: str, time_column: str) -> List[Dict[str, Any]]:
    """Compute a simple trend (average per time bucket)."""
    _ensure_column(ds, column)
    _ensure_column(ds, time_column)
    df = ds.load_dataframe()
    # Ensure time column is datetime
    df[time_column] = pd.to_datetime(df[time_column])
    grouped = df.groupby(df[time_column].dt.to_period("M"))[column].mean().reset_index()
    grouped[time_column] = grouped[time_column].astype(str)
    return grouped.to_dict(orient="records")

def correlation(ds: DataSource, col_a: str, col_b: str) -> Dict[str, float]:
    """Return Pearson correlation between two numeric columns."""
    _ensure_column(ds, col_a)
    _ensure_column(ds, col_b)
    df = ds.load_dataframe()
    corr = df[[col_a, col_b]].corr().iloc[0, 1]
    return {"columns": [col_a, col_b], "pearson": float(corr)}

def value_counts(ds: DataSource, column: str, top_n: int = 10) -> List[Dict[str, Any]]:
    """Return the most common values for a categorical column."""
    _ensure_column(ds, column)
    df = ds.load_dataframe()
    vc = df[column].value_counts().head(top_n).reset_index()
    vc.columns = ["value", "count"]
    return vc.to_dict(orient="records")

def missing_stats(ds: DataSource) -> Dict[str, Any]:
    """Return missing-value statistics for all columns."""
    df = ds.load_dataframe()
    total = len(df)
    missing = df.isnull().sum().to_dict()
    percent = {col: (cnt / total) * 100 for col, cnt in missing.items()}
    return {"total_rows": total, "missing_counts": missing, "missing_percent": percent}
