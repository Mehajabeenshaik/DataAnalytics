import pytest
from sso.local import LocalSSOProvider
from sso.factory import get_sso_provider


def test_provider_name_local():
    assert get_sso_provider().provider_name() == "local"


def test_handle_callback_requires_email():
    p = LocalSSOProvider()
    with pytest.raises(ValueError):
        p.handle_callback({})


def test_handle_callback_ok():
    p = LocalSSOProvider()
    u = p.handle_callback({"email": "A@B.COM", "name": "Ann"})
    assert u.email == "a@b.com"
    assert u.provider == "local"


def test_sso_local_route():
    from fastapi.testclient import TestClient
    from auth import app
    client = TestClient(app)
    r = client.post("/auth/sso/local", json={"email": "admin@example.com", "name": "Admin"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body.get("token_type") == "bearer"