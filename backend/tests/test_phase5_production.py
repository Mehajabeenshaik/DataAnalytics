"""Phase 5 — production hardening tests (config/headers/ready/trust smoke)."""

import importlib

import pytest
from fastapi.testclient import TestClient

from auth import app


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_health_phase5():
    r = _client().get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert "invariant" in data
    assert data.get("phase") == 5
    assert "SQL" in str(data.get("invariant", ""))


def test_ready_endpoint():
    r = _client().get("/ready")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") in ("ready", "not_ready")
    assert "checks" in data
    assert data.get("phase") == 5


def test_security_headers_on_health():
    r = _client().get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "X-Request-ID" in r.headers


def test_request_id_echo():
    c = _client()
    r = c.get("/health", headers={"X-Request-ID": "phase5-test-id"})
    assert r.headers.get("X-Request-ID") == "phase5-test-id"


def test_production_config_rejects_demo_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DEMO_API_KEY", "ak_demo_key_12345")
    monkeypatch.setenv("TENANT_ISOLATION_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    import config as cfg

    # Re-import under production env: fail-closed import must raise,
    # and the live validator must also raise.
    with pytest.raises(RuntimeError):
        importlib.reload(cfg)
    monkeypatch.undo()
    importlib.reload(cfg)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("DEMO_API_KEY", "ak_demo_key_12345")
    monkeypatch.setenv("TENANT_ISOLATION_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    with pytest.raises(RuntimeError):
        cfg.validate_production_config()


def test_production_config_rejects_wildcard_cors(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "y" * 64)
    monkeypatch.setenv("DEMO_API_KEY", "ak_rotated_private_value_123")
    monkeypatch.setenv("TENANT_ISOLATION_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    import config as cfg

    with pytest.raises(RuntimeError):
        importlib.reload(cfg)
    monkeypatch.undo()
    importlib.reload(cfg)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "y" * 64)
    monkeypatch.setenv("DEMO_API_KEY", "ak_rotated_private_value_123")
    monkeypatch.setenv("TENANT_ISOLATION_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        cfg.validate_production_config()


def test_trust_smoke_core_imports():
    import config as cfg

    assert "SQL" in cfg.CORE_INVARIANT
    from policy import critic, confirmation, grounding, injection  # noqa: F401
