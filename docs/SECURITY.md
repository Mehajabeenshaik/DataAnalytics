# Security

## Safety model

The LLM **never generates SQL or Python that is executed**. The architecture is:

1. **Plan** — the LLM selects from an **approved** metric/tool catalog (name, synonyms, description only). It cannot invent metrics or tools.
2. **Execute** — deterministic code (DuckDB / parameterized live SQL) runs the selected metric/tool. All column validation happens here.
3. **Synthesize** — the LLM writes a grounded answer from the exact results returned.

## Data flow

```
Client → Auth + Quota → Plan (approved catalog only) → Execute (timeout + row limits) → Synthesize → Audit + Observability
```

## Tenant isolation

- **Catalog paths**: `data/catalog/<tenant_id>/` — approved metrics and proposals never cross tenants.
- **Audit rows**: every audit record carries `tenant_id`; `export_audit(tenant_id)` filters by tenant in the WHERE clause.
- **Quotas**: keyed by `tenant_id` (`data/quotas/<tenant_id>.json`).
- **Cache keys**: `tenant_id` is hashed into every cache key — two tenants asking the same question never collide.
- **Missing tenant context** → hard fail (401/403), never falls back to a global catalog when `TENANT_ISOLATION_ENABLED=true`.

## PII

- **Detection + masking**: `pii_masker.py` (Presidio + column-name heuristics) masks PII at load time.
- **Encrypted vault**: original values are stored in a Fernet-encrypted vault (`pii_vault.db.enc`) where used.
- **Defense-in-depth**: results are scrubbed again before synthesis (`_scrub_pii_from_results`).
- **Observability logs**: never contain PII — only plan_type, metric/tool names, latency, confidence, error type.
- **Audit details**: question is truncated to 80 chars (preview only), never full raw data.

## Encryption

- **At rest**: PII vault is Fernet-encrypted. Audit/quota/observability files are plaintext JSON/YAML (local-first; document migration to encrypted storage for production).
- **In transit**: TLS is assumed at the deployment layer (reverse proxy / load balancer). The app itself does not terminate TLS.

## Deployment modes

| Mode | LLM | Data location | Notes |
|------|-----|---------------|-------|
| **Local** | Ollama | On-machine | Fully offline; data never leaves the machine |
| **VPC / private** | Ollama or self-hosted vLLM | Customer-controlled network | Air-gapped capable |
| **SaaS multi-tenant** | Cloud LLM (Gemini/NVIDIA) or self-hosted | Provider-managed | Isolation + quotas + audit export |

**Cloud LLM path**: customer data is sent to the LLM provider only as schema cards, metric names/synonyms/descriptions, and result summaries — never raw unmasked rows. We do not train on customer data. For air-gapped deployments, use the local Ollama path.

## What we do NOT do

- No arbitrary SQL from the model (only allowlisted parameterized queries)
- No Python execution from the model
- No direct database access by the LLM
- No unmasked PII sent to the LLM
- No cross-tenant catalog/audit/cache access

## Residual risks

- **Prompt injection** may still attempt to influence planning; mitigated by strict allowlist validation of every plan step.
- **Live DB** requires a true read-only DB role (code checks are defense-in-depth, not a substitute).
- **Local-first storage** (JSON/YAML) is not encrypted at rest for audit/quota files; production deployments should mount encrypted volumes.