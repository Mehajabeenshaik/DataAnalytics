# Threat Model

## Assets

| Asset | Description | Sensitivity |
|-------|-------------|-------------|
| Customer data | Loaded tables (CSV/Parquet/SQLite/live DB) | High |
| PII vault | Encrypted original PII values (`pii_vault.db.enc`) | Critical |
| Metric catalog | Approved metrics + proposals per tenant | Medium |
| Audit logs | Who did what, when, per tenant | High |
| API keys / JWT | Tenant API keys, user JWTs | Critical |
| Observability logs | Plan type, latency, confidence, error type | Low (no PII) |

## Threats

### 1. Prompt injection
**Description**: A user crafts a question that tries to make the LLM planner emit a malicious metric/tool name, filter, or SQL.

**Controls**:
- LLM only selects from the **approved** catalog (name/synonyms/description only)
- Every plan step is validated against `metric_names` / `VALID_TOOL_NAMES` after generation
- Filters are stripped against the allowlist
- No SQL/Python from the model is ever executed

**Residual risk**: The LLM may still be influenced to pick a *valid but irrelevant* metric. Mitigated by the deterministic fallback matcher and low-confidence synthesis.

### 2. Metric hallucination
**Description**: The LLM invents a metric name that doesn't exist.

**Controls**:
- `plan()` rejects any `run_metric` target not in the catalog → `no_match`
- Guided-decoding schema (vLLM) makes invalid targets structurally impossible
- Only `status=approved` metrics are visible to the LLM

**Residual risk**: Low — validation is deterministic and enforced after every generation.

### 3. Cross-tenant leakage
**Description**: Tenant A reads Tenant B's catalog, audit, cache, or data.

**Controls**:
- Separate catalog roots: `data/catalog/<tenant_id>/`
- Audit rows carry `tenant_id`; `export_audit()` filters by tenant in SQL
- Cache keys hash `tenant_id`
- Quota counters keyed by `tenant_id`
- Missing tenant context → hard fail (401/403)
- Widget sessions verify `tenant_key` ownership

**Residual risk**: Low — enforced by construction (separate paths + auth context).

### 4. Resource exhaustion
**Description**: A tenant runs too many queries, too many LLM calls, or a query that returns too many rows / takes too long.

**Controls**:
- Daily query/LLM-call quotas (`tenant_quotas.py`)
- Plan-step caps (`max_plan_steps`)
- Row caps (`apply_row_limit`)
- Query timeouts (`run_with_timeout`)
- File-size caps on upload

**Residual risk**: Medium — quotas are per-day and local-first; a production deployment should add rate limiting at the proxy layer.

### 5. PII exfiltration via model context
**Description**: PII reaches the LLM through schema cards, results, or logs.

**Controls**:
- PII masked at load time (`pii_masker.py`)
- Results scrubbed again before synthesis (`_scrub_pii_from_results`)
- Observability logs contain no PII (only plan_type, metric names, latency, confidence, error)
- Audit details truncate the question to 80 chars

**Residual risk**: Low — masking is defense-in-depth (load-time + pre-synthesis).

### 6. API key / JWT theft
**Description**: An attacker steals a tenant API key or user JWT.

**Controls**:
- API keys are random 48-hex tokens (`ak_...`)
- JWTs are short-lived (30 min default)
- Role checks on admin routes
- Audit logging of login/query actions

**Residual risk**: Medium — no key rotation UI yet; production should add key rotation + revocation.

### 7. Live DB write access
**Description**: A misconfigured live connection allows writes.

**Controls**:
- `connect_live()` performs a write-capability check and refuses writable connections
- SQLite read-only check is fully verified; Postgres/MySQL require a true read-only DB role

**Residual risk**: Medium — the code check is defense-in-depth; the DB role is the real control.

## Summary

| Threat | Severity | Primary control | Residual |
|--------|----------|-----------------|----------|
| Prompt injection | High | Catalog allowlist + validation | Low |
| Metric hallucination | High | Post-generation validation | Low |
| Cross-tenant leakage | Critical | Separate paths + auth context | Low |
| Resource exhaustion | Medium | Quotas + limits + timeouts | Medium |
| PII exfiltration | Critical | Masking + scrubbing | Low |
| Key/JWT theft | High | Random keys + short-lived JWT | Medium |
| Live DB writes | High | Read-only check + DB role | Medium |