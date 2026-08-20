"""
Hard resource limits for agent execution.

Enforces deterministic safety rails that apply regardless of what the LLM
planner produces:
  - max plan steps
  - max result rows (DataFrame / Series / list truncation)
  - query timeout (run_with_timeout)
  - max file size

Phase 2.5 of the DataAnalytics governed-agent roadmap.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, TypeVar

from config import (
    DEFAULT_MAX_PLAN_STEPS,
    DEFAULT_MAX_ROWS_PER_QUERY,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
)

T = TypeVar("T")


class ResourceLimitError(Exception):
    """Raised when a hard resource limit is hit."""


def max_plan_steps(tenant_limit: int | None = None) -> int:
    """Return the plan-step cap (tenant override or global default)."""
    return tenant_limit if tenant_limit is not None else DEFAULT_MAX_PLAN_STEPS


def apply_row_limit(result: Any, max_rows: int | None = None) -> Any:
    """Truncate DataFrame/Series/list results to max_rows. Scalars unchanged.

    Marks truncated DataFrames with attrs["truncated"] = True and
    attrs["original_rows"] so callers can detect truncation.
    """
    limit = max_rows if max_rows is not None else DEFAULT_MAX_ROWS_PER_QUERY
    if limit <= 0:
        return result
    try:
        import pandas as pd

        if isinstance(result, pd.DataFrame):
            if len(result) > limit:
                out = result.head(limit).copy()
                out.attrs["truncated"] = True
                out.attrs["original_rows"] = len(result)
                return out
        if isinstance(result, pd.Series) and len(result) > limit:
            return result.head(limit)
    except Exception:
        pass
    if isinstance(result, list) and len(result) > limit:
        return result[:limit]
    return result


def run_with_timeout(fn: Callable[[], T], seconds: int | None = None) -> T:
    """Run fn with a timeout. Raises ResourceLimitError on timeout."""
    timeout = seconds if seconds is not None else DEFAULT_QUERY_TIMEOUT_SECONDS
    if timeout <= 0:
        return fn()
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            raise ResourceLimitError(f"Query exceeded timeout of {timeout}s")


def enforce_plan_steps(plan_steps: list, tenant_id: str) -> list:
    """Cap the number of plan steps to the tenant's configured limit."""
    from tenant_quotas import get_quota

    quota = get_quota(tenant_id)
    max_steps = quota.max_plan_steps
    if len(plan_steps) > max_steps:
        return plan_steps[:max_steps]
    return plan_steps


def enforce_max_rows(df, tenant_id: str) -> Any:
    """Truncate a result DataFrame to the tenant's max-rows-per-query limit.

    Backward-compatible wrapper around apply_row_limit using the tenant's
    configured max_rows_per_query.
    """
    from tenant_quotas import get_quota

    quota = get_quota(tenant_id)
    return apply_row_limit(df, max_rows=quota.max_rows_per_query)


def enforce_query_timeout(start_time: float, tenant_id: str) -> None:
    """Raise ResourceLimitError if the query has exceeded the tenant timeout."""
    import time

    from tenant_quotas import get_quota

    quota = get_quota(tenant_id)
    elapsed = time.time() - start_time
    if elapsed > quota.query_timeout_seconds:
        raise ResourceLimitError(
            f"Query exceeded timeout of {quota.query_timeout_seconds}s "
            f"for tenant '{tenant_id}'."
        )


def enforce_file_size(file_size_bytes: int, tenant_id: str) -> None:
    """Raise ResourceLimitError if the file exceeds the tenant's max size."""
    from tenant_quotas import get_quota

    quota = get_quota(tenant_id)
    max_bytes = quota.max_file_size_mb * 1024 * 1024
    if file_size_bytes > max_bytes:
        raise ResourceLimitError(
            f"File too large: {file_size_bytes / (1024*1024):.1f}MB exceeds "
            f"tenant limit of {quota.max_file_size_mb}MB."
        )