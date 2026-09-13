# DaAna – Governed Multi-Tenant Analytics Platform

**Core Invariant:** *The LLM never generates or executes SQL or Python. It may only select from human-approved metrics and fixed tools; all execution is deterministic and controlled by this system.*

## Platform Phases
- **Phase 0**: Foundational DuckDB & LLM abstraction framework.
- **Phase 1**: Governed analytics planning and deterministic execution loop (`/ask`, `/metrics`).
- **Phase 2**: Trust, safety, PII masking, post-hoc verification, system-derived confidence, and JSONL audit logging.
- **Phase 3**: Hard multi-tenant isolation, API key / JWT tenant context resolution, tenant-scoped catalogs, data paths, audit logs, and resource quota governance (`/tenants/me`, `/tenants`).
- **Phase 4**: Agentic Policy & Astra Patterns — Verification Critic, consequential action confirmation (`/ask/confirm`), non-evasion retry blocking, grounding checks, prompt-injection resistance, and action-only monitoring (`claimed_tools` vs `observed_tools`).

> [!WARNING]
> `DEFAULT_TENANT_ID` is provided for local demo purposes. When deploying to production environments, enable `TENANT_ISOLATION_ENABLED=True` to enforce strict multi-tenant access control and fail closed on unauthenticated requests.

See [PHASE4.md](file:///c:/Users/bharu/OneDrive/Desktop/f6/phase0/PHASE4.md) for full Phase 4 policy & safety documentation.
