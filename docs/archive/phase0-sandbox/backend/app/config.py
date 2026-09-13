"""
Phase 3 configuration.

Systems rule: configuration is the single source of truth for runtime behaviour.
Secrets must never ship with insecure placeholders.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env without overriding existing env vars
load_dotenv()

# Repo root (phase0/backend/app/config.py -> ../../..)
BASE_DIR = Path(__file__).resolve().parents[2]

# ── Paths ────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "demo.db"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ── LLM provider selection ───────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-3-nano:4b")

# Placeholders for later phases
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/llama-3.1-nemotron-super-49b-v1")
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "")

# ── Security (fail-fast on insecure defaults) ────────────────────────────
_JWT_SECRET_DEFAULT = "change-this-in-production-use-secrets-token"
_raw_jwt = os.getenv("JWT_SECRET_KEY", _JWT_SECRET_DEFAULT)
if _raw_jwt == _JWT_SECRET_DEFAULT:
    raise RuntimeError(
        "JWT_SECRET_KEY is missing or still the insecure placeholder. "
        "Generate one with:\n"
        '  python -c "import secrets; print(secrets.token_hex(32))"'
    )
JWT_SECRET_KEY = _raw_jwt
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))

# ── Resource bounds ───────────────────────────────────────────────────────
DEFAULT_MAX_ROWS_PER_QUERY = int(os.getenv("DEFAULT_MAX_ROWS_PER_QUERY", "100000"))
DEFAULT_MAX_FILE_SIZE_MB = int(os.getenv("DEFAULT_MAX_FILE_SIZE_MB", "50"))
DEFAULT_QUERY_TIMEOUT_SECONDS = int(os.getenv("DEFAULT_QUERY_TIMEOUT_SECONDS", "30"))

# ── Phase 3 Multi-Tenancy & Governance ────────────────────────────────────
TENANT_ISOLATION_ENABLED = os.getenv("TENANT_ISOLATION_ENABLED", "false").lower() in ("true", "1", "yes")
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "default")
DEFAULT_MAX_QUERIES_PER_DAY = int(os.getenv("DEFAULT_MAX_QUERIES_PER_DAY", "1000"))
DEFAULT_MAX_LLM_CALLS_PER_DAY = int(os.getenv("DEFAULT_MAX_LLM_CALLS_PER_DAY", "2000"))
DEFAULT_MAX_PLAN_STEPS = int(os.getenv("DEFAULT_MAX_PLAN_STEPS", "5"))
TENANT_STORE_PATH = os.getenv("TENANT_STORE_PATH", str(BASE_DIR / "data" / "tenants" / "tenants.json"))

# ── Core invariant ───────────────────────────────────────────────────────
CORE_INVARIANT = (
    "The LLM never generates or executes SQL or Python. "
    "It may only select from human‑approved metrics and fixed tools; "
    "all execution is deterministic and controlled by this system."
)

# Backward compatibility aliases for legacy imports
QUERY_TIMEOUT_SECONDS = DEFAULT_QUERY_TIMEOUT_SECONDS
MAX_ROWS_RETURNED = DEFAULT_MAX_ROWS_PER_QUERY
