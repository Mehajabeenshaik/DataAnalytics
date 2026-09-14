# DaAna

Governed analytics agent with a FastAPI backend and a React (Vite) frontend.

The model does not generate or execute SQL or Python. It selects from an approved metric catalog and fixed tools. Execution is deterministic. Answers include confidence, lineage, and policy flags.

---

## Architecture

```
Browser (frontend/)
  → POST /api/v1/session | upload | ask | ask/confirm
FastAPI (backend/app/)
  → plan (allowlisted) → policy critic → execute tools → verify → synthesize
  → DuckDB / stats tools / metric catalog
```

| Layer | Role |
|--------|------|
| Planner / synthesizer | LLM, constrained to catalog + tool names |
| Policy (`policy/`) | Pre-exec checks, confirmation, grounding, injection handling |
| Execution | Deterministic metrics and stats tools |
| Verification | System confidence and flags (not taken from the model alone) |
| Tenants | API-key scoped sessions, quotas, audit |

Core invariant (returned by the API):

> The LLM never generates or executes SQL or Python. It may only select from human-approved metrics and fixed tools; all execution is deterministic and controlled by this system.

---

## Repository layout

```
backend/app/          # API, agent, catalog, tenant, policy
backend/tests/        # pytest suite
frontend/             # Vite + React + TypeScript UI
eval/                 # trust / eval helpers
samples/              # example CSV/XLSX
docs/                 # security, pilot, SSO notes
PRODUCTION.md         # production checklist
```

Historical phase notes live under `docs/archive/`. Runtime code is only under `backend/` and `frontend/`.

---

## Requirements

- Python 3.11+ (3.12 used in CI)
- Node 18+ for the frontend
- Optional: Ollama (or another configured LLM provider)

---

## Backend setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# required
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# optional
cp .env.example .env               # edit provider keys, CORS, etc.

uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001
```

Useful endpoints:

| Method | Path | Notes |
|--------|------|--------|
| GET | `/health` | Liveness, phase, invariant |
| GET | `/ready` | Readiness probes |
| POST | `/api/v1/session` | Header `X-API-Key` |
| POST | `/api/v1/upload` | Multipart file + `session_id` |
| POST | `/api/v1/ask` | JSON: `session_id`, `question` |
| POST | `/api/v1/ask/confirm` | Confirmation token approve/deny |

Default dev API key is often `ak_demo_key_12345` (see tenant seed / `.env.example`). Do not use defaults in production.

---

## Frontend setup

```bash
cd frontend
cp .env.development .env            # or edit in place
npm install
npm run dev
```

`frontend/.env.development` typically contains:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8001
VITE_API_KEY=ak_demo_key_12345
```

If `VITE_API_BASE_URL` is empty, the UI falls back to in-browser mocks.

Open the URL Vite prints (usually `http://localhost:5173`). After sign-in, use **Ask** for questions. The trust panel shows confidence, lineage, and flags from the API response.

---

## Tests

```bash
export JWT_SECRET_KEY=pytest-test-secret-not-for-production-7f3a9b2e
python -m pytest backend/tests -q
```

CI installs from `requirements.txt` and runs the backend suite (see `.github/workflows/ci.yml`). Some live-server scripts may be ignored intentionally.

---

## Configuration notes

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET_KEY` | Required; app refuses the placeholder secret |
| `APP_ENV` | `development` \| `staging` \| `production` |
| `TENANT_ISOLATION_ENABLED` | Should be `true` in production |
| `DEMO_API_KEY` | Must be rotated in production |
| `CORS_ORIGINS` | Comma-separated; avoid `*` in production |
| `LLM_PROVIDER` | e.g. ollama / mock (see config) |

See `PRODUCTION.md` before any real deployment.

---

## Development workflow

1. Start backend on port 8001.  
2. Start frontend with `VITE_API_BASE_URL` pointing at the backend.  
3. Confirm in the browser Network tab: `session` → `upload` → `ask`.  
4. Run pytest before pushing.

CORS must allow the frontend origin (e.g. `http://localhost:5173`).

---

## What this project is not

- Not a text-to-SQL product  
- Not an unrestricted chatbot over your database  
- Not a claim about specific unpublished model internals  

It is a control plane around tool-using LLM calls: allowlists, verification, tenancy, and audit.

---

## License

See `LICENSE` in the repository root.


> **About / repo settings** — owner checklist (set once in GitHub → Settings → General):
>
> - **Description:**
>   `Governed AI analytics agent — LLM never writes SQL. Human-approved metrics only. PII-masked. Audit + lineage on every answer.`
> - **Topics:** `data-analytics` `llm-agent` `governed-ai` `duckdb` `fastapi` `pii-masking` `multi-tenant` `enterprise-ai` `text-to-sql-alternative`
> - License badge should read **Apache-2.0** after the LICENSE re-sync.

Most "chat with your data" products solve the demo problem and create a production problem: the LLM writes SQL (or Python), runs it, and occasionally returns confident nonsense — sometimes over sensitive columns.

DataAnalytics takes the opposite approach.

> The model only **selects** from a human-approved metric catalog.  
> Execution is **deterministic**.  
> PII is **masked before** the model sees results.  
> Every answer carries **confidence and lineage**.

This is not another text-to-SQL wrapper. It is a **systems design for safe analytics agents**.

---

## The problem

Text-to-SQL agents fail in ways that matter to companies:

| Failure | Why it hurts |
|---------|----------------|
| Wrong joins / filters | Decisions on bad numbers |
| Schema hallucination | Broken queries that look fluent |
| PII in model context | Compliance and vendor risk |
| Unbounded queries | Cost and availability risk |
| No audit trail | You cannot explain "why this number?" |

Shipping a chatbot is easy. Shipping **governed** answers is the real product.

---

## How it works

```
Natural-language question
        │
        ▼
┌────────────────────┐
│  0. Sanitize       │  neutralise prompt-injection in question/data
├──────────┬─────────┤
┌──────────▼─────────┐
│  1. Plan           │  LLM chooses approved metrics / stats tools only
└──────────┬─────────┘
          ▼
┌─────────────────────────────┐
│  Policy Critic (code, pre)  │  allowlist + non-evasion + confirmation
└──────────┬──────────────────┘
          ▼
┌───────────────────┐
│  2. Execute       │  Deterministic engine (DuckDB / parameterized live SQL)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  3. Synthesize    │  LLM writes the narrative from scrubbed tool results only
└─────────┬─────────┘
          ▼
   Verify + Ground + Audit (claimed vs observed)
          ▼
   Answer + confidence + flags + lineage + caveats
```

**Invariant:** the model never generates SQL or Python that gets executed, and
every consequence-gated action (export, write-back, report, propose-metric)
pauses for explicit human confirmation *before* anything runs. All policy is
enforced in **code** (the Verification Critic), never via prompt instructions.

---

## What you get

**Analytics**
- Natural-language questions over CSV and live databases
- Auto-seeded metric catalog with propose → approve workflow
- Statistical tools (describe, trends, correlation, outliers, …)
- Multi-dataset registry

**Safety & governance**
- Approved-metric allowlist
- PII detection and masking
- Row limits, plan-step caps, query timeouts
- Tenant isolation for catalog, data paths, and audit

**B2B operations**
- Per-tenant quotas
- Structured observability
- Audit log + export
- JWT auth, API keys for the embeddable widget
- Admin metric-approval console at `/admin` (approve/reject agent proposals)
- Local SSO for pilots; OIDC integration points for Okta/Entra-style IdPs

**Trust evidence**
- Golden + adversarial eval suite
- Published trust report (refusal quality, PII non-leak checks)

---

## Quick start

```bash
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Local model (default)
ollama pull nemotron-3-nano:4b

cp .env.example .env
# Set JWT_SECRET_KEY to a long random secret

# Run the API server (backend)
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001

# Or run the CLI demo
python backend/app/demo.py
```

### Frontend shell (single-page app)

Open `frontend/app/index.html` in a browser (or serve the folder):

```bash
# Option A: just open the file
open frontend/app/index.html

# Option B: serve the folder
cd frontend/app && python -m http.server 8080
# then open http://127.0.0.1:8080
```

The shell talks to `http://127.0.0.1:8001` with API key `ak_demo_key_12345`.
Flow: create session → upload a CSV → ask a question → see answer, confidence, caveats, and lineage.

> **Admin console:** open `http://127.0.0.1:8001/admin` and sign in with an admin
> account to review and approve/reject the metric proposals the agent generates.
> On first boot a secure admin is created — set `BOOTSTRAP_ADMIN_PASSWORD` in
> `.env`, or read the one-time random password the server prints to the console.
> Equivalently, the backend also serves `frontend/app/index.html` at `/app` and
> the chat widget at `/`.

Example:

```text
Question: What is our total revenue?
Answer:   Your total revenue is …
Metric:   total_revenue
Confidence: high
```

### Develop / CI

```bash
# Run the test gate (planner reliability, synonyms, verification, agent, analyst routes)
python -m pytest \
  backend/tests/test_p0_planner_routes.py \
  backend/tests/test_synonym_coverage.py \
  backend/tests/test_verification.py \
  backend/tests/test_agent_phase2.py \
  backend/tests/test_analyst_routes.py \
  backend/tests/test_data_quality.py -q

# Run backend API (port 8001)
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001

# Serve the frontend shell
cd frontend/app && python -m http.server 8080
```

CI (`.github/workflows/ci.yml`) runs the same test modules on `ubuntu-latest` for every push/PR.

With the API running, the analyst UI is also served at `http://127.0.0.1:8001/app`.

### Embeddable chat widget

```html
<script
  src="http://YOUR_HOST:8000/widget/widget.js"
  data-api-key="ak_..."
  data-api-url="http://YOUR_HOST:8000">
</script>
```

---

## LLM providers

| Provider | `.env` | API key |
|----------|--------|---------|
| Ollama (local-first) | `LLM_PROVIDER=ollama` | No |
| Google Gemini | `LLM_PROVIDER=gemini` | Yes |
| NVIDIA NIM | `LLM_PROVIDER=nvidia` | Yes |
| vLLM (self-hosted) | `LLM_PROVIDER=vllm` | Optional |

Air-gapped and VPC-friendly by design: run Ollama (or vLLM) so data never leaves your network.

---

## Deployment modes

| Mode | Fit |
|------|-----|
| **Local** | Laptop demo, offline evaluation |
| **VPC / on-prem** | Enterprise data stays in customer network |
| **Multi-tenant API** | SaaS-style tenants, quotas, audit export |

See [PRODUCTION.md](PRODUCTION.md) (go-live checklist),
[docs/SECURITY.md](docs/SECURITY.md), [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md),
and [docs/SSO.md](docs/SSO.md).

---

## Trust & evaluation

```bash
python eval/run_trust_eval.py --provider mock
pytest test_trust_safety.py -q
```

The [Trust Report](docs/TRUST_REPORT.md) summarizes pass rate, adversarial refusal behavior, and PII leak checks. A **real-LLM run** (local Ollama `nemotron-3-nano:4b`: 82.6% pass, 0 PII leaks) is published in [docs/TRUST_REPORT_ollama.md](docs/TRUST_REPORT_ollama.md), with a plain-English summary for non-engineers in [docs/TRUST.md](docs/TRUST.md). Use a real provider (`ollama` / `gemini`) when you need semantic quality numbers for a pilot.

---

## Design-partner pilots

We designed a two-week pilot path for teams that want governed Q&A on their own data:

1. Deploy local or Docker  
2. Create org / tenant  
3. Load data and approve metrics  
4. Ask questions via demo or widget  
5. Export audit log  

Details: [docs/PILOT.md](docs/PILOT.md).

---

## Architecture principles (for engineers)

1. **Capability, not creativity, at execution time** — the planner picks from an allowlist.  
2. **Determinism where it matters** — aggregates and stats run in code/SQL you control.  
3. **Least data to the model** — mask PII; send results, not raw warehouses.  
4. **Tenant as isolation boundary** — catalog, quotas, audit, and data paths are scoped.  
5. **Observable by default** — structured logs and audit events on agent runs.  
6. **Evidence over claims** — eval suites and a regenerable trust report.

This is the difference between a weekend agent demo and software you can put in front of a security review.

---

## Project layout (high level)

| Path | Role |
|------|------|
| `backend/app/main.py` | FastAPI entry point (`uvicorn backend.app.main:app`) |
| `backend/app/agent_phase2.py` | Plan → execute → synthesize agent primitives |
| `backend/app/agent_phase4.py` | **Governed Phase 4 orchestrator** (`run_governed_ask`) used by `/api/v1/ask` |
| `backend/app/policy/` | **Verification Critic** (code): critic, confirmation, grounding, injection |
| `backend/app/catalog/` | Versioned metric catalog + approval |
| `backend/app/stats_tools.py` | Deterministic statistical tools |
| `backend/app/data_source.py` | CSV / live DB load, profiling, PII |
| `backend/app/tenant/` | Org/tenant identity + isolation |
| `backend/app/sso/` + `backend/app/auth_sso_routes.py` | Local SSO; OIDC hooks in `auth.py` |
| `backend/app/admin_api.py` + `frontend/app/admin.html` | Admin API (org/tenant, catalog approval) + console at `/admin` |
| `backend/app/api_widget.py` + `frontend/embed/` | Embeddable chat bot |
| `backend/tests/` | Test suite |
| `PRODUCTION.md` | Go-live checklist (secrets, isolation, TLS, limits) |
| `eval/` | Trust eval, golden sets, adversarial cases |
| `docs/` | Security, threat model, pilot, trust report |

> **Note on module layout:** live runtime code uses flat modules under
> `backend/app/` (imported by name, e.g. `from config import …`). The
> `backend/app/domain/` + `backend/app/infra/` packages are scaffolding for a
> longer-term layered refactor and are not yet wired into the runtime paths.
>
> **One production tree:** `phase0/` was a historical sandbox only. It is not
> executed in production. Its Phase 4 policy (critic, confirmation, grounding,
> injection) has been merged into `backend/app/policy/` and archived under
> `docs/archive/phase0-sandbox/`. The production agent lives entirely under
> `backend/`.

---

## Roadmap posture

**Done (as of Sep 2026):**
governed Phase 4 agent — the production `/api/v1/ask` runs the headed
orchestrator (`backend/app/agent_phase4.py`) that sanitises input, plans
against an allowlist, applies a **pre-execution Verification Critic**
(allowlist, non-evasion, confirmation), executes deterministically, PII-scrubs,
verifies + grounds the answer, and audits claimed-vs-observed tools. Policy is
enforced in code, not prompts. The core invariant holds: the LLM never
generates or executes SQL/Python. Also: repo hygiene (`.venv` untracked, single
`backend/` tree), fail-closed production config
(`validate_production_config()`), metric catalog + propose/approve workflow,
tenant isolation, audit, safe bootstrap auth, CI that does not rely on a
committed virtualenv.

**Next (design-partner blockers):**
production OIDC against a real IdP (Okta / Entra / Auth0), expanded customer
golden sets from pilots, API-key rotation UI, richer admin UX (catalog
maintenance, quota management).

---

## Who this is for

- Data / platform teams who cannot accept unconstrained text-to-SQL  
- Founders building B2B analytics copilots who need a **safety story**  
- Engineers studying **ML systems** (tool allowlists, isolation, eval, not only prompts)

---

## License & contact

Licensed under the [Apache License 2.0](LICENSE). © 2026 Mehajabeenshaik / DaAna Contributors.

Before commercial licensing or sale, review the contributor/IP checklist in [docs/IP.md](docs/IP.md).

For design-partner pilots or engineering collaboration, open an issue or reach out via the profile linked on GitHub.

---

*Built as a flagship systems project: safe agents are an architecture problem, not a prompt problem.*
