from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Dict
from fastapi import HTTPException

from .tenant.models import TenantQuota, TenantUsage


class QuotaTracker:
    """In-memory daily quota tracker for tenants."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._usage: Dict[str, TenantUsage] = {}

    def _get_current_date_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_usage(self, tenant_id: str) -> TenantUsage:
        today = self._get_current_date_str()
        with self._lock:
            usage = self._usage.get(tenant_id)
            if usage is None or usage.last_reset_date != today:
                usage = TenantUsage(queries_today=0, llm_calls_today=0, last_reset_date=today)
                self._usage[tenant_id] = usage
            return usage.model_copy()

    def check_and_increment_query(self, tenant_id: str, quota: TenantQuota) -> None:
        today = self._get_current_date_str()
        with self._lock:
            usage = self._usage.get(tenant_id)
            if usage is None or usage.last_reset_date != today:
                usage = TenantUsage(queries_today=0, llm_calls_today=0, last_reset_date=today)
                self._usage[tenant_id] = usage

            if usage.queries_today >= quota.max_queries_per_day:
                raise HTTPException(
                    status_code=429,
                    detail=f"Daily query quota exceeded for tenant '{tenant_id}' (limit: {quota.max_queries_per_day})",
                )
            usage.queries_today += 1

    def increment_llm_call(self, tenant_id: str, quota: TenantQuota) -> None:
        today = self._get_current_date_str()
        with self._lock:
            usage = self._usage.get(tenant_id)
            if usage is None or usage.last_reset_date != today:
                usage = TenantUsage(queries_today=0, llm_calls_today=0, last_reset_date=today)
                self._usage[tenant_id] = usage

            if usage.llm_calls_today >= quota.max_llm_calls_per_day:
                raise HTTPException(
                    status_code=429,
                    detail=f"Daily LLM call quota exceeded for tenant '{tenant_id}' (limit: {quota.max_llm_calls_per_day})",
                )
            usage.llm_calls_today += 1

    def reset_usage(self, tenant_id: str) -> None:
        with self._lock:
            if tenant_id in self._usage:
                del self._usage[tenant_id]


_global_tracker = QuotaTracker()


def get_quota_tracker() -> QuotaTracker:
    return _global_tracker
