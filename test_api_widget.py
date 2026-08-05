"""
Tests for the widget API endpoints and tenant management.
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from auth import app
from tenant import init_tenant_db, create_api_key, validate_api_key, revoke_api_key


@pytest.fixture(autouse=True)
def _setup_tenant_db(tmp_path, monkeypatch):
    """Point AUTH_DB_PATH to a temp file for test isolation."""
    db_path = str(tmp_path / "test_auth.db")
    monkeypatch.setattr("tenant.AUTH_DB_PATH", db_path)
    monkeypatch.setattr("auth.AUTH_DB_PATH", db_path)
    # Also ensure auth tables exist
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            hashed_pw TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer'
        );
    """)
    conn.close()
    init_tenant_db()


@pytest.fixture
def tenant():
    return create_api_key("Test Corp", {"theme_color": "#ff0000"}, ["example.com"])


@pytest.fixture
def client():
    return TestClient(app)


# ── Tenant management tests ──────────────────────────────────────────────

class TestTenantManagement:
    def test_create_api_key(self):
        t = create_api_key("Acme Inc", {"max_file_size_mb": 100})
        assert t.api_key.startswith("ak_")
        assert t.company_name == "Acme Inc"
        assert t.settings["max_file_size_mb"] == 100

    def test_validate_api_key(self, tenant):
        result = validate_api_key(tenant.api_key)
        assert result is not None
        assert result.company_name == "Test Corp"
        assert result.settings["theme_color"] == "#ff0000"

    def test_validate_invalid_key(self):
        assert validate_api_key("ak_nonexistent") is None

    def test_allowed_domains_field(self, tenant):
        result = validate_api_key(tenant.api_key)
        assert result.allowed_domains == ["example.com"]

    def test_revoke_api_key(self, tenant):
        assert revoke_api_key(tenant.api_key) is True
        assert validate_api_key(tenant.api_key) is None

    def test_revoke_nonexistent(self):
        assert revoke_api_key("ak_fake") is False


# ── API endpoint tests ───────────────────────────────────────────────────

class TestWidgetAPI:
    def test_no_api_key_returns_422(self, client):
        """Missing X-API-Key header returns 422."""
        r = client.post("/api/v1/session")
        assert r.status_code == 422

    def test_invalid_api_key_returns_401(self, client):
        r = client.post("/api/v1/session", headers={"X-API-Key": "ak_bad"})
        assert r.status_code == 401

    def test_create_session(self, client, tenant):
        r = client.post("/api/v1/session", headers={"X-API-Key": tenant.api_key})
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        assert data["message"]

    def test_tenant_settings(self, client, tenant):
        r = client.get("/api/v1/tenant", headers={"X-API-Key": tenant.api_key})
        assert r.status_code == 200
        data = r.json()
        assert data["company_name"] == "Test Corp"
        assert data["settings"]["theme_color"] == "#ff0000"

    def test_upload_csv(self, client, tenant):
        """Upload a CSV and get baseline analysis."""
        csv_content = "name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,NYC\n"
        r = client.post(
            "/api/v1/upload",
            headers={"X-API-Key": tenant.api_key},
            files={"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["filename"] == "test.csv"
        assert data["rows"] == 3
        assert data["columns"] == 3
        assert data["summary"]
        assert data["session_id"]

    def test_upload_unsupported_format(self, client, tenant):
        r = client.post(
            "/api/v1/upload",
            headers={"X-API-Key": tenant.api_key},
            files={"file": ("test.pdf", io.BytesIO(b"fake"), "application/pdf")},
        )
        assert r.status_code == 400
        assert "Unsupported" in r.json()["detail"]

    def test_session_info_after_upload(self, client, tenant):
        """After uploading, session info should reflect the data."""
        csv = "x,y\n1,10\n2,20\n3,30\n"
        r1 = client.post(
            "/api/v1/upload",
            headers={"X-API-Key": tenant.api_key},
            files={"file": ("data.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        sid = r1.json()["session_id"]

        r2 = client.get(
            f"/api/v1/session/{sid}",
            headers={"X-API-Key": tenant.api_key},
        )
        assert r2.status_code == 200
        info = r2.json()
        assert info["rows"] == 3
        assert info["columns"] == 2
        assert info["filename"] == "data.csv"

    def test_tenant_isolation(self, client, tenant):
        """A session created by one tenant cannot be accessed by another."""
        # Tenant 1 uploads
        csv = "a,b\n1,2\n"
        r1 = client.post(
            "/api/v1/upload",
            headers={"X-API-Key": tenant.api_key},
            files={"file": ("t1.csv", io.BytesIO(csv.encode()), "text/csv")},
        )
        sid = r1.json()["session_id"]

        # Tenant 2 tries to access
        t2 = create_api_key("Other Corp")
        r2 = client.get(
            f"/api/v1/session/{sid}",
            headers={"X-API-Key": t2.api_key},
        )
        assert r2.status_code == 403

    def test_ask_without_upload(self, client, tenant):
        """Asking before uploading should fail."""
        r1 = client.post("/api/v1/session", headers={"X-API-Key": tenant.api_key})
        sid = r1.json()["session_id"]

        r2 = client.post(
            "/api/v1/ask",
            headers={"X-API-Key": tenant.api_key, "Content-Type": "application/json"},
            json={"session_id": sid, "question": "what is the total?"},
        )
        assert r2.status_code == 400

    def test_widget_js_served(self, client):
        """The widget script should be served without auth."""
        r = client.get("/widget/widget.js")
        assert r.status_code == 200
        assert "application/javascript" in r.headers["content-type"]
        assert "Shadow" in r.text or "shadow" in r.text  # Sanity: shadow DOM code is present
