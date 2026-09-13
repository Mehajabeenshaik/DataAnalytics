# Phase 3 — Multi-Tenancy & Isolation

## Overview
Phase 3 evolves DaAna into a hard-isolated multi-tenant platform. Every request is scoped to a verified tenant context. Resource governance, metric catalogs, DuckDB analytical data sources, and audit logs are strictly isolated per tenant.

> [!WARNING]
> `DEFAULT_TENANT_ID` and fallback authentication (`TENANT_ISOLATION_ENABLED=False`) are provided for **local demo convenience only**. In production environments, set `TENANT_ISOLATION_ENABLED=True` to fail closed on unauthenticated requests.

---

## Key Architecture & Features

### 1. Tenant Resolution & Authentication
Protected routes (`/ask`, `/metrics`, `/audit/recent`, `/tenants/me`) resolve tenant context using the following resolution order:
1. `X-API-Key` HTTP Header (e.g. `X-API-Key: key_tenant_a_123`)
2. `Authorization: Bearer <JWT>` HTTP Header (with `tenant_id` claim)
3. Fallback to `DEFAULT_TENANT_ID = "default"` when `TENANT_ISOLATION_ENABLED=False`
4. If `TENANT_ISOLATION_ENABLED=True` and no valid credentials are provided, requests fail closed with `HTTP 401 Unauthorized`.
5. Suspended tenant accounts (`status == "suspended"`) return `HTTP 403 Forbidden`.

### 2. Isolation Boundaries
- **Catalog Isolation**: Metrics are stored and listed per `(tenant_id, name)`. Tenant A cannot view or execute Tenant B's metrics.
- **Data Scoping**: Tenant data files and DuckDB sessions live under `data/tenants/{tenant_id}/`.
- **Audit Logging**: Every audit event includes `tenant_id` and is logged to both global and tenant-isolated `data/tenants/{tenant_id}/audit.log` files.
- **Resource Quotas**: Daily query counts (`max_queries_per_day`), LLM calls, row limits, and timeouts are enforced per tenant. Exceeding limits returns `HTTP 429 Too Many Requests`.

---

## Seed Tenants for Testing & Demo

| Tenant ID | Name | Default API Key |
|-----------|------|-----------------|
| `default` | Default Demo Tenant | `key_default_demo` |
| `tenant_a` | Tenant Alpha | `key_tenant_a_123` |
| `tenant_b` | Tenant Beta | `key_tenant_b_456` |

---

## API Usage Examples

### Query Metrics as Tenant Alpha
```bash
curl -s http://127.0.0.1:8001/metrics \
  -H "X-API-Key: key_tenant_a_123"
```

### Ask Question as Tenant Beta
```bash
curl -s -X POST http://127.0.0.1:8001/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: key_tenant_b_456" \
  -d '{"question": "What is the total revenue?"}'
```

### Fetch Tenant Recent Audit Logs
```bash
curl -s "http://127.0.0.1:8001/audit/recent?limit=5" \
  -H "X-API-Key: key_tenant_a_123"
```

### Create a New Tenant
```bash
curl -s -X POST http://127.0.0.1:8001/tenants \
  -H "Content-Type: application/json" \
  -H "X-API-Key: key_tenant_a_123" \
  -d '{
    "id": "tenant_c",
    "name": "Tenant Gamma",
    "api_keys": ["key_tenant_c_789"],
    "quota": { "max_queries_per_day": 50 }
  }'
```
