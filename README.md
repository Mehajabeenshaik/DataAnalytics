# DaAna

**Governed AI for business data — without letting the model touch your database.**

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
┌───────────────────┐
│  1. Plan          │  LLM chooses approved metrics / stats tools only
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  2. Execute       │  Deterministic engine (DuckDB / parameterized live SQL)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  3. Synthesize    │  LLM writes the narrative from tool results only
└─────────┬─────────┘
          ▼
   Answer + confidence + lineage + caveats
```

**Invariant:** the model never generates SQL or Python that gets executed.

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
> account (local default `admin / admin123`) to review and approve/reject the
> metric proposals the agent generates. Equivalently, the backend also serves
> `frontend/app/index.html` at `/app` and the chat widget at `/`.

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

The [Trust Report](docs/TRUST_REPORT.md) summarizes pass rate, adversarial refusal behavior, and PII leak checks. Use a real provider (`ollama` / `gemini`) when you need semantic quality numbers for a pilot.

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
| `backend/app/agent_phase2.py` | Plan → execute → synthesize agent |
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

---

## Roadmap posture

**Done:** governed agent, catalog workflow, multi-tenant limits, audit, trust eval, local SSO, live DB paths, multi-dataset registry, admin metric-approval console (`/admin`).

**Next:** production OIDC against a real IdP, deeper admin UX (e.g. catalog maintenance, quota management), expanded customer golden sets from pilots.

---

## Who this is for

- Data / platform teams who cannot accept unconstrained text-to-SQL  
- Founders building B2B analytics copilots who need a **safety story**  
- Engineers studying **ML systems** (tool allowlists, isolation, eval, not only prompts)

---

## License & contact

Licensed under the [Apache License 2.0](LICENSE). © 2026 Mehajabeenshaik / DaAna Contributors.

For design-partner pilots or engineering collaboration, open an issue or reach out via the profile linked on GitHub.

---

*Built as a flagship systems project: safe agents are an architecture problem, not a prompt problem.*
