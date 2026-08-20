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
import sys
from pathlib import Path

# Must be set before any project module (config.py) is imported.
# Use setdefault so an externally-provided key (CI/CD secret) is respected.
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "pytest-test-secret-not-for-production-7f3a9b2e",
)
# Provide a test API key so NvidiaProvider() constructs without error in
# tests that call get_provider("nvidia") or build NvidiaProvider() directly.
os.environ.setdefault("NVIDIA_API_KEY", "test-key")

# Add backend/app to sys.path so tests can import flat modules
# (config, auth, agent_phase2, ...) and packages (catalog, tenant, sso).
_APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
