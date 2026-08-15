# SSO & Authentication

## Modes

| Mode | When to use | How |
|------|-------------|-----|
| API key | Embeddable widget, service accounts | `X-API-Key` header |
| Local SSO | Dev / pilots without an IdP | `POST /auth/sso/local` |
| OIDC | Okta, Entra, Auth0, Keycloak | `OIDC_ENABLED=true` + issuer config |

## Local SSO

```bash
curl -s -X POST http://localhost:8000/auth/sso/local \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@acme.com","name":"Admin","tenant_id":"<tenant_id>"}'
```

Response includes `access_token` (JWT). Claims include `email`, `tenant_id`, and `roles`.

If the user belongs to multiple tenants and `tenant_id` is omitted, the API returns `need_tenant_choice` instead of a token.

## JWT claims

- `sub` / `email` — identity
- `tenant_id` — isolation boundary
- `roles` — `viewer` | `analyst` | `admin` | `owner`

## OIDC

Set in `.env`:

```
OIDC_ENABLED=true
OIDC_ISSUER=https://your-idp/...
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_REDIRECT_URI=http://localhost:8000/auth/callback
```

Integration points live in `auth.py`. Until configured, OIDC routes return 501 with clear guidance.

## Security notes

- Never commit real client secrets
- Prefer short-lived JWTs
- Widget API keys are tenant-scoped service credentials, not end-user SSO