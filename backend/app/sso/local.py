from __future__ import annotations
from urllib.parse import urlencode
from .base import SSOUser


class LocalSSOProvider:
    def enabled(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "local"

    def login_url(self, state: str, redirect_uri: str) -> str:
        q = urlencode({"state": state, "redirect_uri": redirect_uri})
        return f"/auth/sso/local/form?{q}"

    def handle_callback(self, params: dict) -> SSOUser:
        email = (params.get("email") or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("email required for local SSO")
        name = (params.get("name") or email.split("@")[0]).strip()
        return SSOUser(
            email=email,
            name=name,
            external_id=f"local:{email}",
            provider="local",
        )