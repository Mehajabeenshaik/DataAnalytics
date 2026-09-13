import pytest
from fastapi import HTTPException
from backend.app.tenant.models import TenantQuota
from backend.app.tenant_quotas import QuotaTracker


def test_quota_under_limit():
    tracker = QuotaTracker()
    quota = TenantQuota(max_queries_per_day=5)

    for _ in range(5):
        tracker.check_and_increment_query("tenant_q", quota)

    usage = tracker.get_usage("tenant_q")
    assert usage.queries_today == 5


def test_quota_exceeded():
    tracker = QuotaTracker()
    quota = TenantQuota(max_queries_per_day=2)

    tracker.check_and_increment_query("tenant_over", quota)
    tracker.check_and_increment_query("tenant_over", quota)

    with pytest.raises(HTTPException) as exc_info:
        tracker.check_and_increment_query("tenant_over", quota)

    assert exc_info.value.status_code == 429
    assert "Daily query quota exceeded" in exc_info.value.detail


def test_quota_reset():
    tracker = QuotaTracker()
    quota = TenantQuota(max_queries_per_day=1)

    tracker.check_and_increment_query("tenant_reset", quota)
    tracker.reset_usage("tenant_reset")

    # Should be allowed again after reset
    tracker.check_and_increment_query("tenant_reset", quota)
    usage = tracker.get_usage("tenant_reset")
    assert usage.queries_today == 1
