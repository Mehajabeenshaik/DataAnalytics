"""Production OIDC login (Auth0 / Okta / Entra ID / Keycloak compatible).

Implements the authorization-code flow:

    GET /auth/login/sso  -> redirect to the IdP authorize endpoint
    GET /auth/callback   -> exchange code, validate ID token, issue local JWT

Discovery, token exchange, and RS256 ID-token validation (via JWKS) use
authlib; HTTP transport is injectable so tests can mock IdP responses
without a live provider.

Security notes:
- `state` is a short-lived HMAC-signed value also stored in a cookie, so
  cross-site callback forgery is rejected.
- The ID token's iss/aud/exp are verified against our configured values and
  its signature against the IdP's published JWKS. `nonce` is bound to state.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from authlib.jose import JsonWebKey
from authlib.jose import jwt as jose_jwt

from config import (
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_DEFAULT_ROLE,
    OIDC_ISSUER,
    OIDC_REDIRECT_URI,
    OIDC_ROLE_CLAIM,
    OIDC_SCOPE,
)

STATE_COOKIE = "daana_oidc_state"
STATE_MAX_AGE_SECONDS = 600


class OIDCError(Exception):
    """OIDC flow failure surfaced to the caller as 401/502."""


class OIDCClient:
    """Thin OIDC relying-party client backed by authlib + httpx."""

    def __init__(
        self,
        issuer: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        scope: str | None = None,
        timeout: float = 10.0,
    ):
        # Resolved at construction time (not def time) so tests can patch
        # the module-level config values.
        # NOTE: `issuer` is kept verbatim for exact `iss` comparison (OIDC
        # requires byte-exact match); `_base` is only for URL building.
        self.issuer = issuer if issuer is not None else OIDC_ISSUER
        self._base = self.issuer.rstrip("/")
        self.client_id = client_id if client_id is not None else OIDC_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else OIDC_CLIENT_SECRET
        self.redirect_uri = redirect_uri if redirect_uri is not None else OIDC_REDIRECT_URI
        self.scope = scope if scope is not None else OIDC_SCOPE
        self.timeout = timeout
        self._discovery: dict[str, Any] | None = None

    # ── transport (overridable in tests) ──────────────────────────────────
    def _get(self, url: str) -> dict[str, Any]:
        resp = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        if resp.status_code != 200:
            raise OIDCError(f"OIDC GET {url} failed ({resp.status_code})")
        return resp.json()

    def _post_token(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        resp = httpx.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise OIDCError(f"OIDC token exchange failed ({resp.status_code})")
        return resp.json()

    # ── discovery ─────────────────────────────────────────────────────────
    def discovery(self) -> dict[str, Any]:
        if self._discovery is None:
            doc = self._get(f"{self._base}/.well-known/openid-configuration")
            for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not doc.get(field):
                    raise OIDCError(f"OIDC discovery missing '{field}'")
            self._discovery = doc
        return self._discovery

    # ── authorize redirect ────────────────────────────────────────────────
    def build_authorize_url(self, state: str, nonce: str) -> str:
        from urllib.parse import urlencode

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "state": state,
            "nonce": nonce,
        }
        sep = "&" if "?" in self.discovery()["authorization_endpoint"] else "?"
        return self.discovery()["authorization_endpoint"] + sep + urlencode(params)

    # ── code exchange + ID token validation ───────────────────────────────
    def exchange_code(self, code: str) -> dict[str, Any]:
        tokens = self._post_token(
            self.discovery()["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if not tokens.get("id_token"):
            raise OIDCError("IdP token response missing id_token")
        return tokens

    def _key_set(self) -> Any:
        jwks = self._get(self.discovery()["jwks_uri"])
        return JsonWebKey.import_key_set(jwks)

    def validate_id_token(self, id_token: str, nonce: str | None = None) -> dict[str, Any]:
        try:
            claims = jose_jwt.decode(
                id_token,
                self._key_set(),
                claims_options={
                    "iss": {"essential": True, "value": self.issuer},
                    "aud": {"essential": True, "value": self.client_id},
                },
            )
            claims.validate(now=int(datetime.now(timezone.utc).timestamp()), leeway=60)
        except Exception as exc:  # authlib raises assorted JoseError subclasses
            raise OIDCError(f"ID token validation failed: {exc}") from exc

        if nonce and claims.get("nonce") != nonce:
            raise OIDCError("ID token nonce mismatch")
        if not claims.get("email"):
            raise OIDCError("ID token missing email claim (check scopes)")
        return dict(claims)


# ── state handling (HMAC-signed, cookie-bound) ───────────────────────────
def make_state(nonce: str) -> str:
    from config import JWT_ALGORITHM, JWT_SECRET_KEY

    payload = {
        "nonce": nonce,
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=STATE_MAX_AGE_SECONDS)).timestamp()),
    }
    return jose_jwt.encode({"alg": JWT_ALGORITHM}, payload, JWT_SECRET_KEY).decode()


def read_state(state: str | None) -> dict[str, Any]:
    from config import JWT_ALGORITHM, JWT_SECRET_KEY

    if not state:
        raise OIDCError("missing state")
    try:
        claims = jose_jwt.decode(state, JWT_SECRET_KEY)
        claims.validate(now=int(datetime.now(timezone.utc).timestamp()))
    except Exception as exc:
        raise OIDCError("invalid or expired state") from exc
    return dict(claims)


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


def map_role(claims: dict[str, Any]) -> str:
    """Map IdP role/group claims to a local role (owner/admin -> admin)."""
    raw: Any = claims.get(OIDC_ROLE_CLAIM) or []
    if isinstance(raw, str):
        raw = [r.strip() for r in raw.split(",") if r.strip()]
    lowered = {str(r).lower() for r in raw}
    if lowered & {"owner", "admin", "admins", "administrator"}:
        return "admin"
    return os.getenv("OIDC_DEFAULT_ROLE", OIDC_DEFAULT_ROLE)

