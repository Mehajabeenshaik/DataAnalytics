from __future__ import annotations


def get_sso_provider():
    from .local import LocalSSOProvider
    return LocalSSOProvider()