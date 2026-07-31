# 📊 DataAnalytics — E-commerce Intelligence Platform

A **production-quality AI-powered analytics dashboard** for Indian e-commerce data, built with Streamlit, FastAPI, and LLM-driven natural language queries.

---

## 🗂️ Project Structure

| File | Purpose |
|------|---------|
| `app.py` | Main Streamlit dashboard (5 pages + admin panel) |
| `app_utils.py` | Cached data loaders, KPI helpers, Plotly chart builders |
| `data_layer.py` | SQLite schema, seed data, `resolve_filter()` (SQL-injection safe) |
| `pii_masker.py` | Presidio-based PII masking → encrypted vault (`pii_vault.db.enc`) |
| `encryption.py` | Fernet symmetric encryption wrapper (`EncryptedDB`) |
| `auth.py` | FastAPI auth server — JWT login, admin/viewer RBAC |
| `auth_middleware.py` | Streamlit-side token validation |
| `audit_logger.py` | Full audit trail (LOGIN, QUERY, PII_ACCESS, etc.) |
| `session_manager.py` | Thread-safe session expiry |
| `llm_provider.py` | LLM abstraction (Gemini via `google.genai` / Ollama) |
| `ai_agent.py` | Core AI reasoning — metric selection, execution, PII scrub, explanation |
| `metrics.py` | Defined business metrics catalog (LLM can only choose from this list) |
| `demo.py` | CLI demo for `ai_agent.ask()` — interactive Q&A in the terminal |
| `import_real_data.py` | Import Olist Brazilian E-Commerce dataset from Kaggle |
| `eval/run_eval.py` | Golden-set evaluation for `ai_agent.ask()` |
| `eval/run_eval_3x.py` | Run the golden-set eval 3× for stability checking |
| `config.py` | All config — raises `RuntimeError` if JWT secret is the default placeholder |
| `conftest.py` | pytest bootstrap — sets `JWT_SECRET_KEY` before imports |

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 2. Configure environment (`.env` file)

This project uses a `.env` file for all secrets and configuration. The file is
**automatically loaded** by `config.py` on startup via `python-dotenv` — no
need to `export` environment variables in every terminal session.

```bash
# Copy the template (safe to commit, contains only placeholders)
cp .env.example .env

# Edit .env and fill in your real values:
#   - JWT_SECRET_KEY  → generate one: python -c "import secrets; print(secrets.token_hex(32))"
#   - GEMINI_API_KEY  → only needed if LLM_PROVIDER=gemini (get one at https://aistudio.google.com/app/apikey)
```

The `.env` file is gitignored and will **never** be committed. `.env.example`
is safe to commit because it contains only placeholder values.

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `JWT_SECRET_KEY` | ✅ yes | — | JWT signing secret (raises `RuntimeError` if missing/placeholder) |
| `LLM_PROVIDER` | no | `ollama` | `ollama` (local) or `gemini` (Google Cloud) |
| `GEMINI_API_KEY` | only if `gemini` | `""` | Google Gemini API key |
| `OLLAMA_BASE_URL` | no | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | no | `qwen2.5-coder:14b` | Ollama model name |
| `DB_ENCRYPTION_KEY` | no | auto | Fernet key for encrypted DBs (auto-generated on first run) |
| `DB_PATH` | no | `ecommerce.db` | Main analytics DB path |
| `PII_VAULT_PATH` | no | `pii_vault.db` | Plaintext PII vault (transient) |
| `PII_VAULT_ENCRYPTED_PATH` | no | `pii_vault.db.enc` | Encrypted PII vault (committed) |
| `AUTH_DB_PATH` | no | `auth.db` | Auth users DB |
| `AUDIT_DB_PATH` | no | `audit.db` | Audit log DB |
| `JWT_EXPIRE_MINUTES` | no | `30` | Token expiry |
| `SESSION_TIMEOUT_MINUTES` | no | `30` | Session timeout |
| `CACHE_TTL_SECONDS` | no | `300` | Data cache TTL |

### 3. Start the auth server (Terminal 1)
```bash
uvicorn auth:app --port 8000
```

### 4. Start the Streamlit dashboard (Terminal 2)
```bash
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

**Default login credentials:**
- `admin / admin123` — full access including Admin Panel
- `viewer / viewer123` — dashboard, charts, AI query, forecasting only

---

## 🔐 Security Architecture

### Encrypted databases at rest
- `ecommerce.db.enc` — main analytics data, Fernet-encrypted
- `pii_vault.db.enc` — original PII (names, emails, phones, addresses), **also encrypted**
- Single shared key via `_get_or_create_key()` in `encryption.py`

### PII masking
All customer PII is replaced with tokens before storage in the analytics DB:
- Names → `Customer 001`, `Customer 002`, …
- Emails → `customer.001@masked.local`
- Phones → `+91-XXXXX-X001`
- Addresses → `[REDACTED], Mumbai`

The original values live only in the encrypted vault, accessible only to admins.

### SQL injection protection
`query_enriched()` no longer accepts raw SQL strings. All filters go through `resolve_filter()` which:
- Validates column names against an explicit allowlist
- Raises `ValueError` for any unknown column
- Binds all values as parameterized `?` placeholders — never string-interpolated

### Auth & secrets
- `JWT_SECRET_KEY` **raises `RuntimeError` at startup** if not set or left as the default placeholder
- RBAC: admin and viewer roles enforced at both FastAPI and Streamlit layers

---

## 🤖 AI Agent Architecture

The AI agent (`ai_agent.py`) uses a **governed metric layer** — the LLM never
writes SQL or aggregation logic. Instead, it follows a 4-step pipeline:

### Step 1: Metric selection (LLM call #1)
`select_metric()` sends the metric catalog (name + synonyms + description only)
to the LLM and asks it to pick exactly one. The LLM **cannot** see column names,
aggregation types, or base filters — only the human-readable description.

- **Pydantic validator** rejects any metric name not in `METRICS`.
- **Filter allowlist stripping** removes any filter key outside
  `ALLOWED_FILTER_COLUMNS`.
- **Malformed JSON** degrades to `no_match` — the agent never guesses.

### Step 2: Deterministic query execution (no LLM)
`run_metric()` combines the metric's `base_filters` with user filters and calls
`query_enriched()`, which enforces the column allowlist and parameterized binding
from `data_layer.py`. The LLM has zero influence over the SQL.

### Step 3: PII defense-in-depth
`scrub_results()` runs Presidio on any string result and redacts detected PII.
This is a second layer — customer PII is already masked at seed time by
`pii_masker.py`.

### Step 4: Explanation (LLM call #2)
`explain()` asks the LLM to summarize the result in plain English. Confidence is
automatically downgraded to `"low"` for small result sets (< 3 data points).

### CLI demo
```bash
python demo.py
```

### Golden-set evaluation
```bash
python eval/run_eval.py          # single run (exits 0 if ≥ 80% accuracy)
python eval/run_eval_3x.py       # 3 consecutive runs for stability check
```

---

## 📊 Dashboard Pages

| Page | Description |
|------|-------------|
| **🏠 Dashboard** | KPI cards + revenue trend + region pie + order status + payment methods + heatmap |
| **📈 Revenue** | Monthly revenue/orders + category performance + filtered data table |
| **🛒 Products** | Top-N products + subcategory treemap with category filter |
| **🤖 AI Query** | Natural language → LLM → `resolve_filter()` → results + chart |
| **🔮 Forecasting** | Prophet model trained on monthly revenue, selectable category + horizon |
| **🛡️ Admin Panel** | Audit log viewer + PII vault inspector + DB reseed (admin only) |

---

## 🤖 AI Query (LLM)

### Using Ollama (local, default)
```bash
ollama pull qwen2.5-coder:14b
ollama serve
```

### Using Gemini
```bash
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=your_key
```

The AI agent uses a **governed metric layer** — the LLM selects from a predefined
metric catalog (`metrics.py`) but never writes SQL. All filters are validated
through `resolve_filter()` before any SQL is built — LLM output can never cause
SQL injection. See the [AI Agent Architecture](#-ai-agent-architecture) section
above for the full 4-step pipeline.

---

## 📥 Importing Real Data (Olist)

The `import_real_data.py` script downloads the Olist Brazilian E-Commerce dataset
from Kaggle and imports it into `ecommerce.db`, replacing the seed data:

```bash
python import_real_data.py            # import (replaces existing data)
python import_real_data.py --force     # force re-download + re-import
```

**Note:** Olist pre-anonymizes customer identity — there are no real names,
emails, or phone numbers in the dataset. `PIIMasker`'s role is defensive-only
here. The script generates placeholder values for the NOT NULL identity columns.

---

## 🧪 Running Tests

```bash
python -m pytest --ignore=test_auth.py -v
```

`test_auth.py` requires the FastAPI auth server to be running on port 8000.

### Test files

| File | Tests | Focus |
|------|-------|-------|
| `test_ai_agent.py` | 20 | Metric routing, filter stripping, `run_metric`, `scrub_results`, `explain` |
| `test_metrics.py` | 10 | Metric catalog integrity, SQL logic isolation, allowlist subset |
| `test_data_layer.py` | 9 | `resolve_filter` parameterization, column allowlist, SQL injection |
| `test_pii_masker.py` | 5 | PII masking, vault encryption at rest, masked data format |
| `test_encryption.py` | — | Fernet encryption wrapper |
| `test_audit_logger.py` | — | Audit trail logging |
| `test_llm_provider.py` | — | Provider selection, Ollama reachability, Gemini API key check |

Key security tests:
- `test_vault_file_is_encrypted_at_rest` — asserts plaintext PII is NOT present in raw vault bytes
- `test_malicious_value_is_parameterized_not_executed` — SQL injection via filter value is harmless
- `test_non_allowlisted_column_raises_value_error` — unknown columns raise `ValueError` immediately
- `test_hallucinated_metric_name_is_rejected` — LLM-invented metric names are stripped, not trusted
- `test_non_allowlisted_filter_is_stripped` — filter keys outside the allowlist are removed
- `test_get_metric_catalog_excludes_sql_logic` — LLM catalog never exposes column/agg/groupby

---

## 🌱 Seed Data

- **250 customers** — Indian names, cities across North/South/East/West regions
- **2,500 orders** — Jan 2023 → Jun 2026, various statuses and payment methods
- **48 products** — 5 categories: Electronics, Clothing, Home & Kitchen, Books, Sports
- **~5,350 line items** — multiple products per order with discounts and cost tracking

Total completed revenue: **₹12.1 Crore**
