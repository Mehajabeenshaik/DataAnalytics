import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App client backed by a fresh auth.db with a known bootstrap admin."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-not-for-prod-32chars-min")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-pass-1")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    # auth.py binds AUTH_DB_PATH into its own namespace at import time, so we
    # must patch the module attribute (not just the env var) per test.
    import backend.app.auth as auth_mod

    db_path = tmp_path / "auth.db"
    if db_path.exists():
        db_path.unlink()
    monkeypatch.setattr(auth_mod, "AUTH_DB_PATH", str(db_path))

    # Import inside the fixture so env vars apply to config.py.
    import backend.app.main as app_module

    auth_mod.init_auth_db()  # seed bootstrap admin deterministically
    return TestClient(app_module.app)


def _login(client, username="admin", password="bootstrap-pass-1"):
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_change_password_success(client):
    headers = _login(client)
    r = client.post(
        "/auth/change-password",
        json={"current_password": "bootstrap-pass-1", "new_password": "new-strong-pass"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "password_changed"

    # Old password no longer works; new one does.
    assert client.post("/auth/login", data={"username": "admin", "password": "bootstrap-pass-1"}).status_code == 401
    assert client.post("/auth/login", data={"username": "admin", "password": "new-strong-pass"}).status_code == 200


def test_change_password_wrong_current(client):
    headers = _login(client)
    r = client.post(
        "/auth/change-password",
        json={"current_password": "totally-wrong", "new_password": "new-strong-pass"},
        headers=headers,
    )
    assert r.status_code == 401


def test_change_password_too_weak(client):
    headers = _login(client)
    r = client.post(
        "/auth/change-password",
        json={"current_password": "bootstrap-pass-1", "new_password": "short"},
        headers=headers,
    )
    assert r.status_code == 400
    assert "10" in r.json()["detail"]


def test_change_password_requires_auth(client):
    r = client.post(
        "/auth/change-password",
        json={"current_password": "x", "new_password": "y"},
    )
    assert r.status_code in (401, 422)