"""
Per-tenant quota tracking for the governed agent.

Tracks usage counters (queries, LLM calls, rows scanned, file uploads) per
tenant so admins can enforce limits and view usage. Local-first: counters
are persisted as JSON under data/quotas/<tenant_id>.json.

Phase 2 of the DataAnalytics governed-agent roadmap.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from config import (
    BASE_DIR,
    DEFAULT_MAX_QUERIES_PER_DAY,
    DEFAULT_MAX_LLM_CALLS_PER_DAY,
    DEFAULT_MAX_ROWS_PER_QUERY,
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_MAX_PLAN_STEPS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
)

_QUOTA_ROOT = Path(BASE_DIR) / "data" / "quotas"
_lock = threading.Lock()


class QuotaExceededError(Exception):
    """Raised when a tenant exceeds a configured quota limit."""


class TenantQuota:
    """Per-tenant quota configuration + live usage counters."""

    def __init__(
        self,
        tenant_id: str,
        max_queries_per_day: int = DEFAULT_MAX_QUERIES_PER_DAY,
        max_llm_calls_per_day: int = DEFAULT_MAX_LLM_CALLS_PER_DAY,
        max_rows_per_query: int = DEFAULT_MAX_ROWS_PER_QUERY,
        max_file_size_mb: int = DEFAULT_MAX_FILE_SIZE_MB,
        max_plan_steps: int = DEFAULT_MAX_PLAN_STEPS,
        query_timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS,
    ):
        self.tenant_id = tenant_id
        self.max_queries_per_day = max_queries_per_day
        self.max_llm_calls_per_day = max_llm_calls_per_day
        self.max_rows_per_query = max_rows_per_query
        self.max_file_size_mb = max_file_size_mb
        self.max_plan_steps = max_plan_steps
        self.query_timeout_seconds = query_timeout_seconds

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "max_queries_per_day": self.max_queries_per_day,
            "max_llm_calls_per_day": self.max_llm_calls_per_day,
            "max_rows_per_query": self.max_rows_per_query,
            "max_file_size_mb": self.max_file_size_mb,
            "max_plan_steps": self.max_plan_steps,
            "query_timeout_seconds": self.query_timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TenantQuota":
        return cls(
            tenant_id=data.get("tenant_id", "default"),
            max_queries_per_day=data.get("max_queries_per_day", 500),
            max_llm_calls_per_day=data.get("max_llm_calls_per_day", 1000),
            max_rows_per_query=data.get("max_rows_per_query", 100_000),
            max_file_size_mb=data.get("max_file_size_mb", 50),
            max_plan_steps=data.get("max_plan_steps", 3),
            query_timeout_seconds=data.get("query_timeout_seconds", 30),
        )


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _quota_path(tenant_id: str) -> Path:
    return _QUOTA_ROOT / f"{tenant_id}.json"


def _load_counters(tenant_id: str) -> dict:
    path = _quota_path(tenant_id)
    if not path.exists():
        return {"day": _day_key(), "queries": 0, "llm_calls": 0, "rows_scanned": 0, "uploads": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"day": _day_key(), "queries": 0, "llm_calls": 0, "rows_scanned": 0, "uploads": 0}
    # Reset counters if the day rolled over.
    if data.get("day") != _day_key():
        data = {"day": _day_key(), "queries": 0, "llm_calls": 0, "rows_scanned": 0, "uploads": 0}
    return data


def _save_counters(tenant_id: str, counters: dict) -> None:
    _QUOTA_ROOT.mkdir(parents=True, exist_ok=True)
    _quota_path(tenant_id).write_text(
        json.dumps(counters, indent=2), encoding="utf-8"
    )


def get_quota(tenant_id: str) -> TenantQuota:
    """Return the quota config for a tenant (defaults if none configured)."""
    path = _QUOTA_ROOT / f"{tenant_id}.quota.json"
    if path.exists():
        try:
            return TenantQuota.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return TenantQuota(tenant_id=tenant_id)


def set_quota(tenant_id: str, quota: TenantQuota) -> None:
    """Persist a custom quota config for a tenant."""
    _QUOTA_ROOT.mkdir(parents=True, exist_ok=True)
    (_QUOTA_ROOT / f"{tenant_id}.quota.json").write_text(
        json.dumps(quota.to_dict(), indent=2), encoding="utf-8"
    )


def record_query(tenant_id: str, rows_scanned: int = 0) -> None:
    """Increment the query counter for a tenant (and rows scanned)."""
    with _lock:
        counters = _load_counters(tenant_id)
        counters["queries"] += 1
        counters["rows_scanned"] += rows_scanned
        _save_counters(tenant_id, counters)


def record_llm_call(tenant_id: str) -> None:
    """Increment the LLM-call counter for a tenant."""
    with _lock:
        counters = _load_counters(tenant_id)
        counters["llm_calls"] += 1
        _save_counters(tenant_id, counters)


def record_upload(tenant_id: str) -> None:
    """Increment the upload counter for a tenant."""
    with _lock:
        counters = _load_counters(tenant_id)
        counters["uploads"] += 1
        _save_counters(tenant_id, counters)


def check_query_quota(tenant_id: str) -> None:
    """Raise QuotaExceededError if the tenant is over its daily query limit."""
    quota = get_quota(tenant_id)
    counters = _load_counters(tenant_id)
    if counters["queries"] >= quota.max_queries_per_day:
        raise QuotaExceededError(
            f"Tenant '{tenant_id}' exceeded daily query limit "
            f"({quota.max_queries_per_day})."
        )


def check_llm_quota(tenant_id: str) -> None:
    """Raise QuotaExceededError if the tenant is over its daily LLM-call limit."""
    quota = get_quota(tenant_id)
    counters = _load_counters(tenant_id)
    if counters["llm_calls"] >= quota.max_llm_calls_per_day:
        raise QuotaExceededError(
            f"Tenant '{tenant_id}' exceeded daily LLM-call limit "
            f"({quota.max_llm_calls_per_day})."
        )


def get_usage(tenant_id: str) -> dict:
    """Return current usage counters for a tenant."""
    counters = _load_counters(tenant_id)
    quota = get_quota(tenant_id)
    return {
        "tenant_id": tenant_id,
        "day": counters["day"],
        "queries": counters["queries"],
        "llm_calls": counters["llm_calls"],
        "rows_scanned": counters["rows_scanned"],
        "uploads": counters["uploads"],
        "quota": quota.to_dict(),
    }