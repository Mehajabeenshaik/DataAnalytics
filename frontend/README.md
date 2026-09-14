# DataAnalytics — Frontend (Bolt UI)

React + TypeScript + Vite frontend for the DataAnalytics platform.
Connects to the governed agent backend (`backend/`) via the widget API.

## Prerequisites

- Node.js 18+ and npm
- Backend running (see [backend README](../backend/README.md) or below)

## Quick start

```bash
# 1. Install dependencies
npm install

# 2. Create env file (or copy the provided .env.development)
cp .env.development .env.development.local

# 3. Start dev server
npm run dev
```

The app runs at `http://localhost:5173` (Vite default).

## Environment variables

Create `frontend/.env.development` (already provided):

```env
VITE_API_BASE_URL=http://127.0.0.1:8001
VITE_API_KEY=ak_demo_key_12345
```

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE_URL` | Backend base URL. Leave empty to use the Vite proxy (see below) or fall back to mock mode. |
| `VITE_API_KEY` | Widget API key (X-API-Key header). Default demo key is `ak_demo_key_12345`. |

### Mock mode

If `VITE_API_BASE_URL` is unset (or empty), the UI uses built-in mock responses.
This is useful for offline demos and portfolio showcases.

### Vite proxy (alternative to full URL)

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8001` (see `vite.config.ts`).
You can use a relative base URL:

```env
VITE_API_BASE_URL=
VITE_API_KEY=ak_demo_key_12345
```

And the proxy will forward requests to the backend. This avoids CORS entirely.

## Running the backend

```bash
# From the repo root
cd backend
pip install -r requirements.txt

# Set required environment variables
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"

# Start
uvicorn backend.app.main:app --reload --port 8001
```

The backend runs at `http://127.0.0.1:8001`.

## CORS configuration

The backend uses `CORS_ORIGINS` env var (comma-separated list).
For local dev, include:

```
http://localhost:5173,http://127.0.0.1:5173
```

If `CORS_ORIGINS` is not set, it defaults to `*` (wildcard, no credentials).
Production deployments **must** set an explicit allowlist.

## API flow (real mode)

1. **Session create** — `POST /api/v1/session` → `{ session_id }`
2. **Auto-upload** — `POST /api/v1/upload` (multipart CSV + session_id)
3. **Ask** — `POST /api/v1/ask` `{ session_id, question }` → governed answer
4. **Confirm** — `POST /api/v1/ask/confirm` `{ confirmation_token, approve }` (when policy requires)

All requests carry the `X-API-Key` header.

## Project structure

```
frontend/
├── src/
│   ├── api/              # apiClient (real backend calls)
│   ├── mock/             # Mock data + fallback apiClient
│   ├── components/       # UI components (AnswerCard, TrustPanel, ConfirmationCard, …)
│   ├── pages/            # Page-level views (AskPage, AdminPage, …)
│   ├── context/          # React context (AppContext)
│   └── types/            # Shared TypeScript types
├── vite.config.ts        # Vite config + proxy
├── tsconfig.app.json     # TypeScript config (path aliases)
└── package.json          # Dependencies + scripts
```

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server |
| `npm run build` | Production build |
| `npm run preview` | Preview production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | TypeScript type checking |

## Trust panel fields

The Trust panel displays:
- **Confidence** — high / medium / low (from backend `confidence`)
- **Plan type** — single_metric / stats_tool / trend_tool / describe_data / confirmation_required
- **Lineage** — metrics and tools used (from `lineage.metrics_or_tools_used`)
- **Safety flags** — PII risk, quota warnings, metric pending, etc.
- **Invariant** — the core safety guarantee (single source of truth from backend)
