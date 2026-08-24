"""OIDC flow tests with a fully mocked IdP (no live provider needed).

Uses a throwaway RSA key so ID-token signatures are genuinely validated
through authlib's JWKS path, exactly as they would be against Auth0/Okta/
Keycloak in production.
"""
import base64
import time

import pytest
from fastapi.testclient import TestClient

ISSUER = "https://idp.example.com/"
CLIENT_ID = "test-client-id"
REDIRECT_URI = "http://testserver/auth/callback"


def _b64int(i: int) -> str:
    return base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


@pytest.fixture()
def rsa_keys():
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nums = key.private_numbers()
    pub = nums.public_numbers
    pub_jwk = {"kty": "RSA", "kid": "test-key", "n": _b64int(pub.n), "e": _b64int(pub.e)}
    priv_jwk = {
        **pub_jwk,
        "d": _b64int(nums.d),
        "p": _b64int(nums.p),
        "q": _b64int(nums.q),
        "dp": _b64int(nums.dmp1),
        "dq": _b64int(nums.dmq1),
        "qi": _b64int(nums.iqmp),
    }
    return priv_jwk, {"keys": [pub_jwk]}


def _id_token(priv_jwk, claims):
    from authlib.jose import jwt as jose_jwt

    return jose_jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, priv_jwk).decode()


@pytest.fixture()
def oidc_env(monkeypatch, tmp_path):
    """Enable OIDC with test IdP coordinates and an isolated auth DB."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-not-for-prod-32chars-min")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    import backend.app.auth as auth_mod
    import backend.app.auth_oidc as oidc_mod

    db_path = tmp_path / "auth.db"
    if db_path.exists():
        db_path.unlink()
    monkeypatch.setattr(auth_mod, "AUTH_DB_PATH", str(db_path))

    # Patch the module-level defaults OIDCClient() picks up.
    monkeypatch.setattr(oidc_mod, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(oidc_mod, "OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(oidc_mod, "OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(oidc_mod, "OIDC_REDIRECT_URI", REDIRECT_URI)
    return oidc_mod


def _mock_idp(monkeypatch, oidc_mod, pub_jwks, token_response=None):
    discovery = {
        "authorization_endpoint": ISSUER + "authorize",
        "token_endpoint": ISSUER + "oauth/token",
        "jwks_uri": ISSUER + ".well-known/jwks.json",
    }
    calls = {}

    def fake_get(self, url):
        calls[url] = True
        if url.endswith("/.well-known/openid-configuration"):
            return dict(discovery)
        if url.endswith("jwks.json"):
            return pub_jwks
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(self, url, data):
        calls["token"] = data
        return token_response or {}

    monkeypatch.setattr(oidc_mod.OIDCClient, "_get", fake_get)
    monkeypatch.setattr(oidc_mod.OIDCClient, "_post_token", fake_post)
    return calls


@pytest.fixture()
def app_client(oidc_env, monkeypatch):
    import backend.app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "OIDC_ENABLED", True)
    from backend.app.auth import init_auth_db

    init_auth_db()
    return TestClient(auth_mod.app)


def _start_login(client):
    r = client.get("/auth/login/sso", follow_redirects=False)
    assert r.status_code == 307, r.text
    state = r.next_request.url.params["state"]
    cookie = client.cookies.get("daana_oidc_state")
    return r, state, cookie


def test_disabled_returns_501(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-not-for-prod-32chars-min")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    import backend.app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "OIDC_ENABLED", False)
    c = TestClient(auth_mod.app)
    assert c.get("/auth/login/sso", follow_redirects=False).status_code == 501
    assert c.get("/auth/callback", follow_redirects=False).status_code == 501


def test_login_redirects_to_authorize_endpoint(app_client, oidc_env, monkeypatch, rsa_keys):
    _, pub = rsa_keys
    _mock_idp(monkeypatch, oidc_env, pub)
    r, state, cookie = _start_login(app_client)
    loc = r.headers["location"]
    assert loc.startswith(ISSUER + "authorize?")
    assert f"client_id={CLIENT_ID}" in loc
    assert "response_type=code" in loc
    assert "nonce=" in loc
    assert state and cookie  # signed state + HttpOnly cookie set


def test_callback_issues_local_jwt(app_client, oidc_env, monkeypatch, rsa_keys):
    priv, pub = rsa_keys
    now = int(time.time())
    nonce_holder = {}
    real_make_state = oidc_env.make_state

    def spy_state(nonce):
        nonce_holder["nonce"] = nonce
        return real_make_state(nonce)

    monkeypatch.setattr(oidc_env, "make_state", spy_state)

    def fake_exchange(self, code):
        tok = _id_token(
            priv,
            {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "sub": "user-123",
                "email": "analyst@acme.com",
                "name": "Analyst One",
                "roles": ["admin"],
                "nonce": nonce_holder.get("nonce"),
                "iat": now,
                "exp": now + 300,
            },
        )
        return {"access_token": "idp-at", "id_token": tok}

    monkeypatch.setattr(oidc_env.OIDCClient, "exchange_code", fake_exchange)
    _mock_idp(monkeypatch, oidc_env, pub)

    r0, state, cookie = _start_login(app_client)
    r = app_client.get(
        "/auth/callback",
        params={"code": "abc", "state": state},
        cookies={"daana_oidc_state": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "admin"          # mapped from the IdP roles claim
    assert body["email"] == "analyst@acme.com"

    # The issued local JWT must authenticate against /auth/me.
    me = app_client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "analyst@acme.com"


def test_callback_rejects_state_mismatch(app_client, oidc_env, monkeypatch, rsa_keys):
    _, pub = rsa_keys
    _mock_idp(monkeypatch, oidc_env, pub)
    r = app_client.get(
        "/auth/callback",
        params={"code": "abc", "state": "forged"},
        cookies={"daana_oidc_state": "also-forged"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_callback_rejects_bad_signature(app_client, oidc_env, monkeypatch, rsa_keys):
    """An ID token signed by a key NOT in the IdP's JWKS must be rejected."""
    _, pub = rsa_keys
    other_priv, _ = rsa_keys
    now = int(time.time())
    tok = _id_token(
        other_priv,
        {"iss": ISSUER, "aud": CLIENT_ID, "email": "x@y.com", "exp": now + 300},
    )

    def fake_exchange(self, code):
        return {"id_token": tok}

    monkeypatch.setattr(oidc_env.OIDCClient, "exchange_code", fake_exchange)
    _mock_idp(monkeypatch, oidc_env, pub)

    r0, state, cookie = _start_login(app_client)
    r = app_client.get(
        "/auth/callback",
        params={"code": "abc", "state": state},
        cookies={"daana_oidc_state": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_callback_rejects_idp_error(app_client, oidc_env, monkeypatch, rsa_keys):
    _, pub = rsa_keys
    _mock_idp(monkeypatch, oidc_env, pub)
    r0, state, cookie = _start_login(app_client)
    r = app_client.get(
        "/auth/callback",
        params={"error": "access_denied", "state": state},
        cookies={"daana_oidc_state": cookie},
        follow_redirects=False,
    )
    assert r.status_code == 401

