"""
conftest.py — pytest session bootstrap.

Sets required environment variables BEFORE any project module is imported.
This is necessary because config.py raises RuntimeError at import time when
JWT_SECRET_KEY is absent or equal to the insecure placeholder sentinel — a
deliberate security control that prevents the app from starting with a
guessable secret in production.

Tests run with a deterministic test-only key that is NOT the production
sentinel value, so the security check passes without weakening it.
"""
import os

# Must be set before any project module (config.py) is imported.
# Use setdefault so an externally-provided key (CI/CD secret) is respected.
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-test-secret-not-for-production-7f3a9b2e",
)
