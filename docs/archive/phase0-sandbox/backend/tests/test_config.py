import os
import pytest

from backend.app.config import JWT_SECRET_KEY, CORE_INVARIANT

def test_jwt_secret_set(monkeypatch):
    # Ensure JWT_SECRET_KEY is set and not default placeholder
    assert JWT_SECRET_KEY != "change-this-in-production-use-secrets-token"
    assert isinstance(JWT_SECRET_KEY, str)
    # Core invariant should be a non‑empty string
    assert CORE_INVARIANT.startswith("The LLM never generates")
