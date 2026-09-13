from __future__ import annotations

from typing import Any, Dict, Optional

from duckdb import DuckDBPyConnection

from .catalog.models import MetricDefinition
from .data_source import DataSource
from .config import QUERY_TIMEOUT_SECONDS, MAX_ROWS_RETURNED

def _safe_sql(metric: MetricDefinition, filters: Optional[Dict[str, Any]] = None) -> str:
    """Create a safe SQL statement from a metric definition.

    * The metric's ``sql_template`` is the only SQL the executor may run.
    * ``filters`` are applied as a simple ``WHERE column = value`` clause for
      columns listed in ``allowed_filters``.
    * No user‑provided raw SQL is ever concatenated.
    """
    base_sql = metric.sql_template.strip().rstrip(";")
    if not filters:
        return base_sql
    # Validate filter columns
    invalid = [c for c in filters if c not in metric.allowed_filters]
    if invalid:
        raise ValueError(f"Filter columns not allowed for metric {metric.name}: {invalid}")
    where_clauses = []
    params = []
    for col, val in filters.items():
        where_clauses.append(f"{col} = ?")
        params.append(val)
    where_sql = " AND ".join(where_clauses)
    sql = f"{base_sql} WHERE {where_sql}"
    return sql, params

def run_metric(metric: MetricDefinition, data_source: DataSource, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a single approved metric against the ``DataSource``.

    Returns a dictionary containing the metric name, the raw result (as a list of
    records), row count and a minimal lineage record showing the executed SQL.
    """
    conn: DuckDBPyConnection = data_source.duckdb_conn
    # Build safe SQL and parameters
    if filters:
        sql, params = _safe_sql(metric, filters)
    else:
        sql = metric.sql_template.strip().rstrip(";")
        params = []
    # Apply row limit for safety
    limited_sql = f"SELECT * FROM ({sql}) LIMIT {MAX_ROWS_RETURNED}"
    # Execute with timeout – DuckDB does not have a native timeout, so we rely on
    # the surrounding request limits defined in ``config.py`` (e.g., uvicorn timeout).
    result_df = conn.execute(limited_sql, params).fetchdf()
    return {
        "metric": metric.name,
        "result": result_df.to_dict(orient="records"),
        "row_count": len(result_df),
        "lineage": {"sql": limited_sql},
    }
