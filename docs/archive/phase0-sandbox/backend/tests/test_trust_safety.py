from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_endpoint_phase2():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["phase"] >= 2
    assert "invariant" in data


def test_ask_endpoint_trust_safety():
    response = client.post("/ask", json={"question": "What is the total revenue?"})
    assert response.status_code == 200
    data = response.json()
    assert "confidence" in data
    assert "flags" in data
    assert isinstance(data["flags"], list)
    assert "lineage" in data
    assert "invariant" in data
    assert "verification" in data


def test_audit_recent_endpoint():
    response = client.get("/audit/recent?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
