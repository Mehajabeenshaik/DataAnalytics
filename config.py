import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "ecommerce.db"))

PII_VAULT_PATH = os.getenv("PII_VAULT_PATH", str(BASE_DIR / "pii_vault.db"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-mini")

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-in-production-use-secrets-token")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
AUTH_DB_PATH = os.getenv("AUTH_DB_PATH", str(BASE_DIR / "auth.db"))
AUDIT_DB_PATH = os.getenv("AUDIT_DB_PATH", str(BASE_DIR / "audit.db"))

DB_ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY", "")
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
