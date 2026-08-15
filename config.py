import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if it exists (local dev). In production, real env vars
# take precedence — load_dotenv() does NOT override existing env vars.
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "ecommerce.db"))

PII_VAULT_PATH = os.getenv("PII_VAULT_PATH", str(BASE_DIR / "pii_vault.db"))
# Encrypted PII vault path — clearly distinct from a plaintext file.
# PIIMasker reads/writes through EncryptedDB using this path.
PII_VAULT_ENCRYPTED_PATH = os.getenv("PII_VAULT_ENCRYPTED_PATH", str(BASE_DIR / "pii_vault.db.enc"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/llama-3.1-nemotron-super-49b-v1")
# Default local model: nemotron-3-nano:4b (Nemotron 3 Nano, 4B params).
# Fallback/alternative: qwen2.5-coder:14b - larger, code-tuned, more accurate
# on structured JSON output but needs more VRAM. Use if Nemotron underperforms:
#   OLLAMA_MODEL=qwen2.5-coder:14b
# Model choice matters significantly for structured reasoning tasks like SQL/filter
# generation. Larger code-tuned models (e.g. qwen2.5-coder:14b) produce far more
# accurate column names, operator choices, and parameterized WHERE clauses than
# smaller general-purpose models. Accuracy on ambiguous natural-language queries
# degrades sharply below ~7B parameters or without code fine-tuning.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-3-nano:4b")

# Self-hosted vLLM server settings — only needed if LLM_PROVIDER=vllm
# Serve your own OpenAI-compatible endpoint with:
#   vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))

_JWT_SECRET_DEFAULT_SENTINEL = "change-this-in-production-use-secrets-token"
_raw_jwt_secret = os.getenv("JWT_SECRET_KEY", _JWT_SECRET_DEFAULT_SENTINEL)
if _raw_jwt_secret == _JWT_SECRET_DEFAULT_SENTINEL:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set (or is still the insecure placeholder). "
        "Set a strong random secret before starting the app:\n"
        "  export JWT_SECRET_KEY=$(python -c \"import secrets; print(secrets.token_hex(32))\")"
    )
JWT_SECRET_KEY = _raw_jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", str(BASE_DIR / "auth.db"))
AUDIT_DB_PATH = os.getenv("AUDIT_DB_PATH", str(BASE_DIR / "audit.db"))

DB_ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY", "")
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))

# ── Phase 2: Tenant quotas & resource limits ─────────────────────────────
# Default per-tenant limits. Overridable per-tenant via tenant_quotas.set_quota().
DEFAULT_MAX_QUERIES_PER_DAY = int(os.getenv("DEFAULT_MAX_QUERIES_PER_DAY", "500"))
DEFAULT_MAX_LLM_CALLS_PER_DAY = int(os.getenv("DEFAULT_MAX_LLM_CALLS_PER_DAY", "1000"))
DEFAULT_MAX_ROWS_PER_QUERY = int(os.getenv("DEFAULT_MAX_ROWS_PER_QUERY", "100000"))
DEFAULT_MAX_FILE_SIZE_MB = int(os.getenv("DEFAULT_MAX_FILE_SIZE_MB", "50"))
DEFAULT_MAX_PLAN_STEPS = int(os.getenv("DEFAULT_MAX_PLAN_STEPS", "3"))
DEFAULT_QUERY_TIMEOUT_SECONDS = int(os.getenv("DEFAULT_QUERY_TIMEOUT_SECONDS", "30"))

# ── Phase 3: Tenant isolation & SSO ──────────────────────────────────────
TENANT_ISOLATION_ENABLED = os.getenv("TENANT_ISOLATION_ENABLED", "true").lower() == "true"
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "default")  # local demo only

# ── Tenant store backend ──────────────────────────────────────────────────
# TENANT_STORE=file      → file-based store under data/tenants/ (default)
# TENANT_STORE=postgres  → PostgreSQL store (requires TENANT_DATABASE_URL)
TENANT_STORE = os.getenv("TENANT_STORE", "file").strip().lower()
TENANT_DATABASE_URL = os.getenv(
    "TENANT_DATABASE_URL",
    os.getenv("DATABASE_URL", ""),  # fall back to generic DATABASE_URL if set
)

OIDC_ENABLED = os.getenv("OIDC_ENABLED", "false").lower() == "true"
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")

