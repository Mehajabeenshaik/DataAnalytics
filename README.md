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
| `llm_provider.py` | LLM abstraction (Gemini / Ollama) |
| `config.py` | All config — raises `RuntimeError` if JWT secret is the default placeholder |
| `conftest.py` | pytest bootstrap — sets `JWT_SECRET_KEY` before imports |

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 2. Set environment variables
```bash
# Required — must be a strong random secret in production
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# Optional — set to 'gemini' to use Google Gemini instead of local Ollama
export LLM_PROVIDER=ollama          # default
export GEMINI_API_KEY=your_key_here # only needed if LLM_PROVIDER=gemini
```

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

The AI extracts filter conditions from plain English, validated through `resolve_filter()` before any SQL is built — LLM output can never cause SQL injection.

---

## 🧪 Running Tests

```bash
python -m pytest --ignore=test_auth.py -v
```

`test_auth.py` requires the FastAPI auth server to be running on port 8000.

Key security tests:
- `test_vault_file_is_encrypted_at_rest` — asserts plaintext PII is NOT present in raw vault bytes
- `test_malicious_value_is_parameterized_not_executed` — SQL injection via filter value is harmless
- `test_non_allowlisted_column_raises_value_error` — unknown columns raise `ValueError` immediately

---

## 🌱 Seed Data

- **250 customers** — Indian names, cities across North/South/East/West regions
- **2,500 orders** — Jan 2023 → Jun 2026, various statuses and payment methods
- **48 products** — 5 categories: Electronics, Clothing, Home & Kitchen, Books, Sports
- **~5,350 line items** — multiple products per order with discounts and cost tracking

Total completed revenue: **₹12.1 Crore**
