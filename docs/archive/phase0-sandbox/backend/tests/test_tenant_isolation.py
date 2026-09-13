from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.catalog.service import CatalogService
from backend.app.catalog.models import MetricDefinition
from backend.app.audit_logger import log_entry, get_recent
from backend.app.tenant import tenant_data_dir, assert_same_tenant

client = TestClient(app)


def test_catalog_isolation():
    cat = CatalogService()
    # Add unique metric to Tenant A
    metric_a = MetricDefinition(
        name="metric_a_only",
        tenant_id="tenant_a",
        description="Metric A",
        sql_template="SELECT 1",
        status="approved",
    )
    from backend.app.catalog.store import set as store_set
    store_set(metric_a)

    approved_a = cat.list_approved("tenant_a")
    approved_b = cat.list_approved("tenant_b")

    names_a = [m.name for m in approved_a]
    names_b = [m.name for m in approved_b]

    assert "metric_a_only" in names_a
    assert "metric_a_only" not in names_b


def test_audit_isolation():
    log_entry({"question": "Q from A"}, tenant_id="tenant_a")
    log_entry({"question": "Q from B"}, tenant_id="tenant_b")

    recent_a = get_recent(limit=10, tenant_id="tenant_a")
    recent_b = get_recent(limit=10, tenant_id="tenant_b")

    for item in recent_a:
        assert item.get("tenant_id") == "tenant_a"

    for item in recent_b:
        assert item.get("tenant_id") == "tenant_b"


def test_data_path_isolation():
    path_a = tenant_data_dir("tenant_a")
    path_b = tenant_data_dir("tenant_b")

    assert str(path_a) != str(path_b)
    assert "tenant_a" in str(path_a)
    assert "tenant_b" in str(path_b)


def test_assert_same_tenant_raises_on_mismatch():
    with pytest.raises(Exception) as exc:
        assert_same_tenant("tenant_a", "tenant_b")
    assert "403" in str(exc.value) or "Access denied" in str(exc.value)


def test_ask_isolation_enforcement(monkeypatch):
    monkeypatch.setattr("backend.app.main.TENANT_ISOLATION_ENABLED", True)

    # Missing API key should return 401 when isolation enabled
    response = client.post("/ask", json={"question": "What is the total revenue?"})
    assert response.status_code == 401

    # Valid Tenant A API key should work
    res_a = client.post(
        "/ask",
        json={"question": "What is the total revenue?"},
        headers={"X-API-Key": "key_tenant_a_123"},
    )
    assert res_a.status_code == 200
    assert res_a.json()["tenant_id"] == "tenant_a"
