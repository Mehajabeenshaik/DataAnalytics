# Production Checklist — DaAna / DataAnalytics

Use this checklist as your go-live gate. Each item is a hard requirement for
running governed analytics in front of real customers or a security review.

## Secrets & configuration

- [ ] Set `JWT_SECRET_KEY` to a long random value
      (`python -c "import secrets; print(secrets.token_hex(32))"`).
      The app **refuses to start** with the insecure placeholder.
- [ ] Keep `.env` out of version control (it is gitignored). Ship
      `.env.example` with placeholders only.
- [ ] Use a real, rotated `DB_ENCRYPTION_KEY` (Fernet) so the PII vault is
      decryptable only in your environment.
- [ ] Never paste real keys into `docker-compose.yml`; pass them via a host
      `.env` and `${VAR:-default}` substitution.

## Tenant & isolation

- [ ] Set `TENANT_ISOLATION_ENABLED=true` so every request carries a valid
      tenant context.
- [ ] Remove reliance on `DEFAULT_TENANT_ID` (local-demo only).
- [ ] For multi-tenant SaaS, switch `TENANT_STORE=postgres` and point
      `TENANT_DATABASE_URL` at your managed Postgres.

## Database access

- [ ] Use a **read-only database role** for live DB connections that the
      agent queries against.
- [ ] Keep write access (reseed, uploads, PII vault) on a separate privileged
      role used only by trusted paths.
- [ ] Backup strategy for the catalog (`data/catalog/`), the audit log, and
      the Postgres tenant store.

## Network & TLS

- [ ] Terminate TLS at a reverse proxy (nginx / Caddy / cloud LB) in front of
      the service on port 8001.
- [ ] Keep the LLM provider internal / air-gapped when possible
      (Ollama or private vLLM) so data never leaves your network.
- [ ] Configure rate limiting at the proxy layer (per IP and per tenant).
- [ ] Restrict `CORS_ORIGINS` to your real frontend/embed origins —
      do not ship the dev-wide `*` default in production.

## Authentication & access control

- [ ] Rotate and manage widget API keys via admin endpoints, not hardcoded
      demo keys.
- [ ] Wire real OIDC (Okta / Entra / Auth0 / Descope) — see `docs/SSO.md`.
      Until then OIDC routes return 501 with explicit guidance.
- [ ] Enforce admin-only access to `/admin/*`, `/auth/register`, and metric
      approval routes (already role-gated: `admin` role required).

## Resource & safety limits

- [ ] Set per-tenant quotas and row/plan-step/timeout limits to match your
      data size and cost budget (see `.env.example`, `Phase 2` section).
- [ ] Confirm the safety invariant end-to-end: **the LLM never generates
      executable SQL/Python** — it only *chooses* pre-approved metrics/tools,
      and execution is deterministic.
- [ ] Run the full trust eval with your **production** LLM provider
      (`python eval/run_trust_eval.py --provider <prod>`), not just `mock`.

## Observability

- [ ] Enable structured logging with `LOG_LEVEL` set appropriately.
- [ ] Ship logs and audit events to a central store.
- [ ] Ensure `/health` is reachable through the proxy for orchestrator
      probes (and the Docker healthcheck).

## Recommended architecture

```
Internet → TLS Proxy → DaAna (8001) → DuckDB / Read-only Postgres
                     ↘ Ollama or private vLLM (air-gapped)
```

## References

- `docs/SECURITY.md` — safety model & invariants
- `docs/THREAT_MODEL.md` — trusted-compute review
- `docs/SSO.md` — local SSO + OIDC integration points
- `docs/TRUST_REPORT.md` — regenerable trust/eval report
- `docs/PILOT.md` — two-week design-partner pilot path