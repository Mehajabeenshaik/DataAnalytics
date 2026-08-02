# DataAnalytics — Governed Local AI Analyst

A **fully local** AI-powered data analyst that runs on Ollama with Nemotron. No API keys required for normal use. Upload any CSV/Parquet file, ask questions in plain English, and get governed, PII-protected answers.

## Quick Start

### 1. Install dependencies
```bash
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 2. Set up Ollama (local LLM, no API key needed)
```bash
# Install Ollama: https://ollama.com
ollama pull nemotron-3-nano:4b
ollama serve
```

Alternative model if Nemotron isn't available or underperforms:
```bash
ollama pull qwen2.5-coder:14b
# Then set OLLAMA_MODEL=qwen2.5-coder:14b in .env
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env — only JWT_SECRET_KEY is required:
#   python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Run the demo
```bash
python demo.py
```

### 5. (Optional) Start the auth server
```bash
uvicorn auth:app --port 8000
```

## Project Structure

| File | Purpose |
|------|---------|
| `agent_phase2.py` | **Main agent**: planner -> execute -> synthesize loop |
| `agent_core.py` | Phase 1 core: metric selection, execution, explanation |
| `data_source.py` | DuckDB abstraction with auto PII masking on load |
| `metric_factory.py` | Auto-generates metric catalog from data profile |
| `stats_tools.py` | 6 deterministic statistical tools (describe, correlation, etc.) |
| `llm_provider.py` | LLM providers: Ollama (default), Gemini, NVIDIA NIM |
| `pii_masker.py` | Presidio-based PII masking with encrypted vault |
| `encryption.py` | Fernet symmetric encryption wrapper |
| `config.py` | All config — Ollama is default, no API key needed |
| `demo.py` | CLI demo — interactive Q&A with the governed agent |
| `eval/run_eval.py` | Golden-set evaluation |
| `eval/run_eval_3x.py` | 3x stability check |
| `auth.py` | FastAPI auth server (JWT, RBAC) |
| `audit_logger.py` | Audit trail logging |

## LLM Providers

| Provider | Setting | API Key Required? |
|----------|---------|-------------------|
| **Ollama** (default) | `LLM_PROVIDER=ollama` | No — fully local |
| NVIDIA NIM | `LLM_PROVIDER=nvidia` | Yes — `NVIDIA_API_KEY` |
| Gemini | `LLM_PROVIDER=gemini` | Yes — `GEMINI_API_KEY` |

Default model: `nemotron-3-nano:4b` (local, 4B params)
Fallback: `qwen2.5-coder:14b` (local, 14B params, more accurate JSON)

## Agent Architecture

The agent (`agent_phase2.py`) uses a **planner -> execute -> synthesize** loop:

1. **Planner** (LLM, temp 0.05): Routes to a metric, stats tool, multi-step plan, or propose-metric
2. **Execute** (deterministic, no LLM): Runs metrics/stats tools with column validation
3. **Synthesize** (LLM, temp 0.3): Writes grounded answer with confidence + caveats

### Safety model
- LLM only picks from the metric catalog and allowed tool names
- Filters stripped against allowlist
- No raw SQL from LLM ever executed
- PII masked at load time + scrubbed from results before synthesis

### PII Protection
- **Load time**: `data_source.py` auto-detects PII columns via Presidio and masks them before data is queryable
- **Defense-in-depth**: `agent_phase2.py` scrubs any PII from results before sending to LLM
- **Encrypted vault**: Original PII stored in Fernet-encrypted `pii_vault.db.enc`

## Running Tests

```bash
python -m pytest --ignore=test_auth.py -v
```

## Golden-Set Evaluation

```bash
python eval/run_eval.py          # single run
python eval/run_eval_3x.py       # 3x stability check
```

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `JWT_SECRET_KEY` | yes | — | JWT signing secret |
| `LLM_PROVIDER` | no | `ollama` | `ollama`, `nvidia`, or `gemini` |
| `OLLAMA_MODEL` | no | `nemotron-3-nano:4b` | Local model name |
| `NVIDIA_API_KEY` | only if `nvidia` | `""` | NVIDIA NIM API key |
| `GEMINI_API_KEY` | only if `gemini` | `""` | Google Gemini API key |