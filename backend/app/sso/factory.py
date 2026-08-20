from __future__ import annotations
import os


def get_sso_provider():
    name = (os.getenv("SSO_PROVIDER") or "local").strip().lower()
    from .local import LocalSSOProvider
    return LocalSSOProvider()