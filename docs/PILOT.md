# 2-Week Design-Partner Pilot

This guide walks a design partner through a 2-week pilot of the governed AI data analyst agent.

## Week 1 — Setup & first questions

### Step 1: Deploy

**Option A — Local (fastest)**
```bash
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
ollama pull nemotron-3-nano:4b
cp .env.example .env
# set JWT_SECRET_KEY
python demo.py
```

**Option B — Docker**
```bash
docker compose up --build
```

### Step 2: Create org + tenant + user

```bash
python -m tenant.cli create-org "Acme Corp"
python -m tenant.cli create-tenant <org_id> "Acme Analytics"
python -m tenant.cli create-user admin@acme.com --name "Admin"
python -m tenant.cli add-user admin@acme.com --role admin --tenant <tenant_id>
```

### Step 3: Load data

```bash
# In demo.py, choose option 2 and enter your CSV path
# Or via the widget API:
#   POST /api/v1/upload  (X-API-Key: ak_demo_key_12345)
```

### Step 4: Seed + approve metrics

On first load, auto metrics are seeded as approved. To review:
```bash
python -m catalog.cli list-pending
python -m catalog.cli list-versions
```

### Step 5: Ask questions

```bash
python demo.py
# > What is total revenue by region?
# > Show me the trend of orders over time
# > Which category has the highest average order value?
```

### Step 6: Export audit log

```bash
# CLI
python -m tenant.cli export-audit <tenant_id> --days 30

# API (admin JWT required)
curl -H "Authorization: Bearer <admin_jwt>" \
  "http://localhost:8000/admin/tenants/<tenant_id>/audit/export?days=30&format=csv"
```

## Week 2 — Governance & validation

### Success criteria checklist

- [ ] Agent answers 80%+ of the pilot question set correctly (no hallucinated metrics)
- [ ] Every answer includes confidence + lineage (which metric/tool, filters, notes)
- [ ] PII columns are masked in schema card and results
- [ ] Propose-metric flow creates a pending proposal; admin approves/rejects via CLI or API
- [ ] Only approved metrics appear in the LLM planner prompt
- [ ] Audit export returns only that tenant's records
- [ ] Quota/limit enforcement fires (set a low quota, hit it, see 429 or low-confidence message)
- [ ] Cross-tenant isolation verified (create a second tenant, confirm no catalog/audit/cache leakage)

### Pilot question set (suggested)

| # | Question | Expected plan type |
|---|----------|-------------------|
| 1 | What is total revenue? | single_metric |
| 2 | Show revenue by region | stats_tool (group_compare) |
| 3 | Describe the data | stats_tool (describe) |
| 4 | Any outliers in revenue? | stats_tool (anomaly_detect) |
| 5 | What's the weather today? | no_match (decline) |
| 6 | Median revenue (not in catalog) | propose_metric |

### Feedback template

For each question, record:
- Question text
- Plan type chosen
- Answer + confidence
- Was the answer correct? (yes / no / partial)
- Any caveats or issues

## Rollout decision

After the 2-week pilot, review:
1. **Accuracy** — did the agent answer correctly on the pilot set?
2. **Governance** — did the approve/reject workflow feel usable?
3. **Isolation** — did cross-tenant tests pass?
4. **Performance** — were query timeouts / row caps acceptable?

If yes → proceed to production packaging (SSO, warehouse connectors, metering).