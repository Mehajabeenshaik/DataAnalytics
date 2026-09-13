from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

from ..config import (
    DEFAULT_MAX_QUERIES_PER_DAY,
    DEFAULT_MAX_LLM_CALLS_PER_DAY,
    DEFAULT_MAX_ROWS_PER_QUERY,
    DEFAULT_MAX_PLAN_STEPS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    DEFAULT_MAX_FILE_SIZE_MB,
)


class TenantQuota(BaseModel):
    max_queries_per_day: int = Field(default=DEFAULT_MAX_QUERIES_PER_DAY)
    max_llm_calls_per_day: int = Field(default=DEFAULT_MAX_LLM_CALLS_PER_DAY)
    max_rows_per_query: int = Field(default=DEFAULT_MAX_ROWS_PER_QUERY)
    max_plan_steps: int = Field(default=DEFAULT_MAX_PLAN_STEPS)
    query_timeout_seconds: int = Field(default=DEFAULT_QUERY_TIMEOUT_SECONDS)
    max_file_size_mb: int = Field(default=DEFAULT_MAX_FILE_SIZE_MB)


class TenantUsage(BaseModel):
    queries_today: int = 0
    llm_calls_today: int = 0
    last_reset_date: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))


class Tenant(BaseModel):
    id: str
    name: str
    status: str = "active"  # active | suspended
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    api_keys: List[str] = Field(default_factory=list)
    quota: TenantQuota = Field(default_factory=TenantQuota)


class TenantContext(BaseModel):
    tenant_id: str
    tenant_name: str
    api_key_used: Optional[str] = None
    auth_method: str = "demo"  # api_key | jwt | demo
    quota: TenantQuota = Field(default_factory=TenantQuota)
