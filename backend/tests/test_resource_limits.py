"""Tests for Phase 2: resource limits enforcement."""

import pandas as pd
import pytest

from resource_limits import (
    enforce_plan_steps,
    enforce_max_rows,
    enforce_file_size,
    enforce_query_timeout,
    ResourceLimitError,
)
from tenant_quotas import TenantQuota, set_quota


@pytest.fixture
def limited_tenant(tmp_path, monkeypatch):
    """Set a tenant quota with tight resource limits and isolate the store."""
    import tenant_quotas
    monkeypatch.setattr(tenant_quotas, "_QUOTA_ROOT", tmp_path / "quotas")
    quota = TenantQuota(
        tenant_id="limited-tenant",
        max_plan_steps=2,
        max_rows_per_query=5,
        max_file_size_mb=1,
        query_timeout_seconds=0,
    )
    set_quota("limited-tenant", quota)
    return quota


def test_enforce_plan_steps_caps(limited_tenant):
    steps = [1, 2, 3, 4]
    capped = enforce_plan_steps(steps, "limited-tenant")
    assert len(capped) == 2


def test_enforce_plan_steps_does_not_grow(limited_tenant):
    steps = [1]
    capped = enforce_plan_steps(steps, "limited-tenant")
    assert len(capped) == 1


def test_enforce_max_rows_truncates(limited_tenant):
    df = pd.DataFrame({"a": range(10)})
    capped = enforce_max_rows(df, "limited-tenant")
    assert len(capped) == 5


def test_enforce_max_rows_keeps_smaller(limited_tenant):
    df = pd.DataFrame({"a": range(3)})
    capped = enforce_max_rows(df, "limited-tenant")
    assert len(capped) == 3


def test_enforce_file_size_raises(limited_tenant):
    with pytest.raises(ResourceLimitError):
        enforce_file_size(2 * 1024 * 1024, "limited-tenant")  # 2MB > 1MB


def test_enforce_file_size_ok(limited_tenant):
    enforce_file_size(500 * 1024, "limited-tenant")  # 0.5MB < 1MB


def test_enforce_query_timeout_raises(limited_tenant):
    import time
    start = time.time() - 5  # pretend 5s elapsed
    with pytest.raises(ResourceLimitError):
        enforce_query_timeout(start, "limited-tenant")