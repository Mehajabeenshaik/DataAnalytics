# DaAna – Phase 0 Foundations & Invariant

**Core Invariant**: *The LLM never generates or executes SQL or Python. It may only be used later for planning and synthesis under strict allowlists.*

## What this repository contains (Phase 0)
- Clean layout with a Python package under `backend/app/`.
- Configuration system (`config.py`) that loads from env / `.env` and fails fast on insecure secrets.
- Minimal LLM‑provider abstraction (`llm_provider.py`) – a local Ollama implementation.
- Simple CSV‑to‑DuckDB data source (`data_source.py`) that produces a table profile.
- Structured logging foundation.
- FastAPI skeleton exposing `/health` and `/` endpoints that surface the invariant.
- pytest test suite and a GitHub Actions CI workflow.

## What is **not** built yet
- Metric catalog, planner, synthesis, agent loop, multi‑tenancy, verification critic, Astra patterns, etc.

## How to run locally
```bash
# 1️⃣ Install dependencies
python -m pip install -r requirements.txt

# 2️⃣ Create a secret (or copy .env.example → .env and replace the placeholder)
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# 3️⃣ (Optional) Run a local Ollama model
ollama pull nemotron-3-nano:4b

# 4️⃣ Run the test suite
pytest backend/tests -q

# 5️⃣ Start the API
uvicorn backend.app.main:app --reload --port 8001
#    → http://127.0.0.1:8001/health
```

---

*Phase 0 establishes a secure, deterministic foundation for the DaAna analytics agent platform.*
