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

Production SSO is implemented as a standard OAuth2 **authorization-code flow**
(`backend/app/auth_oidc.py`, using `authlib` for discovery, token exchange,
and RS256 ID-token validation via the IdP's JWKS). Works with any compliant
IdP — verified request shapes for Auth0 and Keycloak.

### Env vars

```bash
OIDC_ENABLED=true
OIDC_ISSUER=https://your-tenant.us.auth0.com/     # must match token 'iss' exactly
OIDC_CLIENT_ID=...
OIDC_CLIENT_SECRET=...
OIDC_REDIRECT_URI=http://localhost:8001/auth/callback
# Optional
OIDC_ROLE_CLAIM=roles          # claim holding groups/roles (default: roles)
OIDC_DEFAULT_ROLE=viewer       # local role when no admin/owner role is claimed
OIDC_SCOPE=openid email profile
```

### Flow

1. `GET /auth/login/sso` → 307 redirect to the IdP authorize endpoint with a
   signed `state` (also stored in an HttpOnly cookie) and a `nonce`.
2. User authenticates at the IdP; IdP redirects to `/auth/callback?code=...&state=...`.
3. Server verifies `state` matches the signed cookie, exchanges the code at
   the IdP token endpoint, validates the ID token signature against the
   IdP's published JWKS plus exact `iss`/`aud`/`exp`, and binds the `nonce`.
4. Roles are mapped from `OIDC_ROLE_CLAIM` (`owner`/`admin` → local `admin`,
   otherwise `OIDC_DEFAULT_ROLE`); tenant linkage is resolved from the
   tenant identity layer when available.
5. DaAna issues its own short-lived JWT (`sub`, `email`, `role`,
   `tenant_id`, `roles`). Local username/password login keeps working.

### Auth0 setup (5 minutes)

1. Applications → Applications → **Create Application** → *Regular Web Applications*.
2. Allowed Callback URLs: `http://localhost:8001/auth/callback`
3. Copy Domain / Client ID / Client Secret:
   - `OIDC_ISSUER=https://<domain>/`
   - `OIDC_CLIENT_ID=<client id>`
4. To send roles, enable **RBAC → Add permissions in the access token** and add
   an Action on *Login / Post Login* adding `event.auth0Authorization.roles`
   (or your custom namespace claim) as `roles`; set `OIDC_ROLE_CLAIM=roles`.

### Keycloak setup

1. Create a realm → Clients → **Create client**: Client type *OpenID Connect*,
   Client ID = your client id; turn **Client authentication** ON (confidential).
2. Valid redirect URIs: `http://localhost:8001/auth/callback`
3. Credentials tab → copy the Client secret.
4. `OIDC_ISSUER=http://localhost:8080/realms/<realm>/`
5. Roles live in the token's `roles` claim (realm/client roles) — default
   `OIDC_ROLE_CLAIM=roles` already matches.

### Testing without a live IdP

```bash
python -m pytest backend/tests/test_oidc.py -q
```

The tests spin up a throwaway RSA keypair, publish it as the IdP JWKS, sign
real ID tokens, and assert the full flow: redirect shape, code exchange,
signature validation (rejects foreign keys), state binding, role mapping,
and IdP error handling.

## Security notes

- Never commit real client secrets
- Prefer short-lived JWTs
- Widget API keys are tenant-scoped service credentials, not end-user SSO