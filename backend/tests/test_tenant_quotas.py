"""Tests for Phase 2: tenant quotas and resource limits."""

import pandas as pd
import pytest

from tenant_quotas import (
    TenantQuota,
    set_quota,
    get_quota,
    record_query,
    record_llm_call,
    check_query_quota,
    check_llm_quota,
    get_usage,
    QuotaExceededError,
)
from resource_limits import enforce_plan_steps, enforce_max_rows


@pytest.fixture
def low_quota_tenant(tmp_path, monkeypatch):
    """Set a tenant quota with a tiny query limit and isolate the store."""
    import tenant_quotas
    monkeypatch.setattr(tenant_quotas, "_QUOTA_ROOT", tmp_path / "quotas")
    quota = TenantQuota(
        tenant_id="test-tenant",
        max_queries_per_day=2,
        max_llm_calls_per_day=2,
        max_rows_per_query=3,
        max_plan_steps=1,
    )
    set_quota("test-tenant", quota)
    return quota


def test_quota_defaults():
    q = TenantQuota(tenant_id="x")
    assert q.max_queries_per_day >= 1
    assert q.max_llm_calls_per_day >= 1


def test_set_and_get_quota(low_quota_tenant):
    q = get_quota("test-tenant")
    assert q.max_queries_per_day == 2
    assert q.max_llm_calls_per_day == 2


def test_query_quota_exceeded(low_quota_tenant):
    record_query("test-tenant")
    record_query("test-tenant")
    with pytest.raises(QuotaExceededError):
        check_query_quota("test-tenant")


def test_llm_quota_exceeded(low_quota_tenant):
    record_llm_call("test-tenant")
    record_llm_call("test-tenant")
    with pytest.raises(QuotaExceededError):
        check_llm_quota("test-tenant")


def test_usage_reports_counters(low_quota_tenant):
    record_query("test-tenant", rows_scanned=10)
    rec = get_usage("test-tenant")
    assert rec["queries"] == 1
    assert rec["rows_scanned"] == 10


def test_enforce_plan_steps(low_quota_tenant):
    steps = [1, 2, 3]
    capped = enforce_plan_steps(steps, "test-tenant")
    assert len(capped) == 1


def test_enforce_max_rows(low_quota_tenant):
    df = pd.DataFrame({"a": range(10)})
    capped = enforce_max_rows(df, "test-tenant")
    assert len(capped) == 3