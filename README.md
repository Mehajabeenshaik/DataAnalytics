# DataAnalytics

**Governed AI Data Analyst Agent**

A local-first AI agent that answers natural-language questions about your data — without ever letting an LLM write SQL, touch your database directly, or see unmasked PII.

---

## Why this exists

Most "chat with your data" tools let an LLM generate SQL against your schema.  
This is fast to build but unreliable: wrong answers look confident, and sensitive data can leak.

This project takes a different approach:

- The LLM only **selects** from a predefined catalog of metrics and statistical tools
- All query execution is done by deterministic code
- PII is masked before the model ever sees the data
- Every answer includes confidence and clear lineage

---

## How it works

```
Question
   │
   ▼
┌────────────────────────────────────────────┐
│  1. Plan        → LLM chooses metric/tool  │
│  2. Execute     → Deterministic code runs  │
│  3. Synthesize  → LLM writes the answer    │
└────────────────────────────────────────────┘
   │
   ▼
{
  "answer": "Total revenue was $121 million",
  "confidence": "high",
  "metric_used": "total_revenue",
  "filters_used": {...}
}
```

The model never generates SQL or Python that gets executed.

---

## Features

- Natural language questions over your data
- Automatic metric catalog generation
- Statistical tools (describe, value counts, correlation, trends, outliers, etc.)
- Static files (CSV) and live database connections
- PII detection and masking
- Multiple LLM backends: Ollama (local), Gemini, NVIDIA NIM, vLLM
- Response caching
- JWT authentication and audit logging
- Embeddable chat widget

---

## Quick Start

```bash
# 1. Install dependencies
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 2. Pull a local model (default)
ollama pull nemotron-3-nano:4b

# 3. Configure
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# Paste the output into JWT_SECRET_KEY in .env

# 4. Run the demo
python demo.py
```

Example:

```
Question: What is our total revenue?
Answer: Your total revenue is over $121 million
   Metric:     total_revenue
   Confidence: high
```

---

## Using different LLM providers

| Provider     | Setting in `.env`      | Needs API key? |
|--------------|------------------------|----------------|
| Ollama       | `LLM_PROVIDER=ollama`  | No             |
| Google Gemini| `LLM_PROVIDER=gemini`  | Yes            |
| NVIDIA NIM   | `LLM_PROVIDER=nvidia`  | Yes            |
| vLLM         | `LLM_PROVIDER=vllm`    | No (self-hosted)|

No code changes are required — just update the environment variable.

---

## Static vs Live data

**Static (default)**
```python
source = DataSource(name="sales")
source.load_file("sample_sales_data.csv")
```

**Live database**
```python
source = DataSource(name="sales")
source.connect_live(
    connection_string="postgresql://readonly_user:***@host/db",
    refresh_mode="ttl",
    ttl_seconds=30,
)
```

Live mode only accepts read-only connections.

---

## Safety guarantees

| Guarantee                        | How it is enforced                          |
|----------------------------------|---------------------------------------------|
| No SQL injection                 | Parameterized and allowlisted queries only  |
| No invented metrics or tools     | Strict validation against the real catalog  |
| No unmasked PII sent to the LLM  | Masked at load time + second scrub          |
| No confident wrong answers       | Falls back to `no_match` or low confidence  |
| No writable live connections     | Rejected before any query runs              |

---

## Project structure

| File / Folder            | Purpose                                      |
|--------------------------|----------------------------------------------|
| `agent_phase2.py`        | Main agent (plan → execute → synthesize)     |
| `agent_core.py`          | Metric execution                             |
| `stats_tools.py`         | Statistical analysis tools                   |
| `data_source.py`         | Data loading and profiling                   |
| `metric_factory.py`      | Auto-generates the metric catalog            |
| `llm_provider.py`        | LLM backend abstraction                      |
| `pii_masker.py`          | PII detection and masking                    |
| `api_widget.py`          | API for the embeddable chat widget           |
| `benchmarks/`            | Latency measurement                          |
| `eval/`                  | Accuracy evaluation                          |
| `demo.py`                | Interactive command-line demo                |

---

## Evaluation

```bash
python eval/run_eval.py        # single run
python eval/run_eval_3x.py     # three runs for stability
```

---

## Deployment modes

### 1. Local demo (single tenant)
- `DEFAULT_TENANT_ID=default` — the only mode where a missing tenant context falls back.
- `python demo.py` works unchanged.

### 2. Multi-tenant SaaS
- Set `TENANT_ISOLATION_ENABLED=true` (default).
- Every request must carry a valid tenant context (JWT with `tenant_id` or `X-API-Key` for the widget).
- Each tenant gets its own catalog root (`data/catalog/<tenant_id>/`), quota counters, observability log, and audit records.

### 3. VPC / on-prem
- Same isolation model; runs fully offline with Ollama or a self-hosted vLLM server.
- No external IdP, Redis, or Postgres required for the core path.

---

## Identity

| Method   | When to use                                    | Notes                                          |
|----------|------------------------------------------------|------------------------------------------------|
| API key  | Widget embed (end users don't log in)          | `X-API-Key` header, identifies the company     |
| JWT      | Interactive dashboard / admin                  | Username + password → short-lived JWT          |
| OIDC/SSO | B2B pilots with SSO requirements               | `/auth/login/sso`, `/auth/callback`, `/auth/token` integration points (see `auth.py`) |

After SSO login, the IdP user is mapped to our tenant store and the app issues its own short-lived JWT carrying `tenant_id` + roles.

**RBAC roles:** `owner` / `admin` (approve metrics, export audit, manage org/tenants) · `analyst` (ask questions, propose metrics) · `viewer` (read answers only).

---

## Threat model note

Cross-tenant isolation is enforced **by construction**, not by convention:
- **Separate catalog roots** — `CatalogService(tenant_id=...)` points to `data/catalog/<tenant_id>/`
- **Auth context** — every `ask()`, catalog, and audit call receives an `AuthContext` with `tenant_id`
- **Audit scoping** — `export_audit()` always filters by `tenant_id` in the WHERE clause
- **Cache keys** — tenant_id is hashed into every cache key
- No fallback to a global catalog when `TENANT_ISOLATION_ENABLED=true` (missing context → 401/403)

---

## Tenant administration

```bash
# Create an org, tenant, and user
python -m tenant.cli create-org "Acme Corp"
python -m tenant.cli create-tenant <org_id> "Acme Analytics"
python -m tenant.cli create-user admin@acme.com --name "Admin"
python -m tenant.cli add-user admin@acme.com --role admin --tenant <tenant_id>

# Usage & audit
python -m tenant.cli usage <tenant_id>
python -m tenant.cli export-audit <tenant_id> --days 30
```

Per-tenant catalog path on disk:
```
data/catalog/<tenant_id>/
  current/metrics.yaml
  proposals/<uuid>.yaml
  history/v001/...
```

Admin API (protected by admin/owner role):
```
GET  /admin/orgs
POST /admin/orgs
GET  /admin/tenants?org_id=...
POST /admin/tenants
GET  /admin/tenants/{tenant_id}/usage
GET  /admin/tenants/{tenant_id}/catalog
POST /admin/tenants/{tenant_id}/catalog/approve/{proposal_id}
GET  /admin/tenants/{tenant_id}/audit/export?days=30
```

---

## Phase 2: Quotas, resource limits, observability

- `tenant_quotas.py` — per-tenant daily query/LLM-call counters, row caps, file size caps. Persisted under `data/quotas/`.
- `resource_limits.py` — deterministic enforcement of plan-step caps, max result rows, query timeouts.
- `observability.py` — structured JSONL telemetry per tenant under `data/observability/`.
- `audit_logger.py` — every audit record now carries `tenant_id`; `export_audit(tenant_id)` returns only that tenant's records.

## Tests

```bash
python -m pytest test_catalog.py test_tenant_quotas.py test_tenant_isolation.py test_rbac.py test_catalog_tenant_scoped.py -q
```

---

## Known limitations

- Best suited for one primary dataset per running instance
- Live database read-only checks are fully verified on SQLite; use proper read-only roles on Postgres/MySQL
- Some derived metrics are approximations and should be reviewed
- File-based tenant store (`data/tenants/`) is local-first; documented migration path to Postgres later
- SSO endpoints are production-shaped stubs — the IdP HTTP calls are marked integration points in `auth.py`

---

## License

[Add your license here]
