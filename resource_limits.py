"""
Resource limits enforcement for the governed agent.

Enforces hard limits on plan steps, query row counts, and query timeouts
per tenant. These are deterministic safety rails that apply regardless of
what the LLM planner produces.

Phase 2 of the DataAnalytics governed-agent roadmap.
"""

from __future__ import annotations

import time
from typing import Any

from tenant_quotas import get_quota, QuotaExceededError


class ResourceLimitError(Exception):
    """Raised when a resource limit is exceeded."""


def enforce_plan_steps(plan_steps: list, tenant_id: str) -> list:
    """Cap the number of plan steps to the tenant's configured limit."""
    quota = get_quota(tenant_id)
    max_steps = quota.max_plan_steps
    if len(plan_steps) > max_steps:
        return plan_steps[:max_steps]
    return plan_steps


def enforce_max_rows(df, tenant_id: str) -> Any:
    """Truncate a result DataFrame to the tenant's max-rows-per-query limit.

    Returns the (possibly truncated) DataFrame. The caller can compare
    len(result) to the original to detect truncation.
    """
    quota = get_quota(tenant_id)
    max_rows = quota.max_rows_per_query
    if hasattr(df, "__len__") and len(df) > max_rows:
        return df.head(max_rows)
    return df


def enforce_query_timeout(start_time: float, tenant_id: str) -> None:
    """Raise ResourceLimitError if the query has exceeded the tenant timeout."""
    quota = get_quota(tenant_id)
    elapsed = time.time() - start_time
    if elapsed > quota.query_timeout_seconds:
        raise ResourceLimitError(
            f"Query exceeded timeout of {quota.query_timeout_seconds}s "
            f"for tenant '{tenant_id}'."
        )


def enforce_file_size(file_size_bytes: int, tenant_id: str) -> None:
    """Raise ResourceLimitError if the file exceeds the tenant's max size."""
    quota = get_quota(tenant_id)
    max_bytes = quota.max_file_size_mb * 1024 * 1024
    if file_size_bytes > max_bytes:
        raise ResourceLimitError(
            f"File too large: {file_size_bytes / (1024*1024):.1f}MB exceeds "
            f"tenant limit of {quota.max_file_size_mb}MB."
        )