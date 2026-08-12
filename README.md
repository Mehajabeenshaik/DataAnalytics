# DataAnalytics

**Governed AI Data Analyst Agent**

A local-first AI agent that answers natural-language questions about your data — without ever letting an LLM write SQL, touch your database directly, or see unmasked PII.

---

## Why this exists

Most "chat with your data" tools let an LLM generate SQL against your schema.  
This is fast to build but unreliable: wrong answers look confident, and sensitive data can leak.

This project takes a different approach:

- The LLM only **selects** from a predefined catalog of metrics and statistical tools
- All query execution is done by deterministic code
- PII is masked before the model ever sees the data
- Every answer includes confidence and clear lineage

---

## How it works

```
Question
   │
   ▼
┌────────────────────────────────────────────┐
│  1. Plan        → LLM chooses metric/tool  │
│  2. Execute     → Deterministic code runs  │
│  3. Synthesize  → LLM writes the answer    │
└────────────────────────────────────────────┘
   │
   ▼
{
  "answer": "Total revenue was $121 million",
  "confidence": "high",
  "metric_used": "total_revenue",
  "filters_used": {...}
}
```

The model never generates SQL or Python that gets executed.

---

## Features

- Natural language questions over your data
- Automatic metric catalog generation
- Statistical tools (describe, value counts, correlation, trends, outliers, etc.)
- Static files (CSV) and live database connections
- PII detection and masking
- Multiple LLM backends: Ollama (local), Gemini, NVIDIA NIM, vLLM
- Response caching
- JWT authentication and audit logging
- Embeddable chat widget

---

## Quick Start

```bash
# 1. Install dependencies
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 2. Pull a local model (default)
ollama pull nemotron-3-nano:4b

# 3. Configure
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# Paste the output into JWT_SECRET_KEY in .env

# 4. Run the demo
python demo.py
```

Example:

```
Question: What is our total revenue?
Answer: Your total revenue is over $121 million
   Metric:     total_revenue
   Confidence: high
```

---

## Using different LLM providers

| Provider     | Setting in `.env`      | Needs API key? |
|--------------|------------------------|----------------|
| Ollama       | `LLM_PROVIDER=ollama`  | No             |
| Google Gemini| `LLM_PROVIDER=gemini`  | Yes            |
| NVIDIA NIM   | `LLM_PROVIDER=nvidia`  | Yes            |
| vLLM         | `LLM_PROVIDER=vllm`    | No (self-hosted)|

No code changes are required — just update the environment variable.

---

## Static vs Live data

**Static (default)**
```python
source = DataSource(name="sales")
source.load_file("sample_sales_data.csv")
```

**Live database**
```python
source = DataSource(name="sales")
source.connect_live(
    connection_string="postgresql://readonly_user:***@host/db",
    refresh_mode="ttl",
    ttl_seconds=30,
)
```

Live mode only accepts read-only connections.

---

## Safety guarantees

| Guarantee                        | How it is enforced                          |
|----------------------------------|---------------------------------------------|
| No SQL injection                 | Parameterized and allowlisted queries only  |
| No invented metrics or tools     | Strict validation against the real catalog  |
| No unmasked PII sent to the LLM  | Masked at load time + second scrub          |
| No confident wrong answers       | Falls back to `no_match` or low confidence  |
| No writable live connections     | Rejected before any query runs              |

---

## Project structure

| File / Folder            | Purpose                                      |
|--------------------------|----------------------------------------------|
| `agent_phase2.py`        | Main agent (plan → execute → synthesize)     |
| `agent_core.py`          | Metric execution                             |
| `stats_tools.py`         | Statistical analysis tools                   |
| `data_source.py`         | Data loading and profiling                   |
| `metric_factory.py`      | Auto-generates the metric catalog            |
| `llm_provider.py`        | LLM backend abstraction                      |
| `pii_masker.py`          | PII detection and masking                    |
| `api_widget.py`          | API for the embeddable chat widget           |
| `benchmarks/`            | Latency measurement                          |
| `eval/`                  | Accuracy evaluation                          |
| `demo.py`                | Interactive command-line demo                |

---

## Evaluation

```bash
python eval/run_eval.py        # single run
python eval/run_eval_3x.py     # three runs for stability
```

---

## Known limitations

- Best suited for one primary dataset per running instance
- Live database read-only checks are fully verified on SQLite; use proper read-only roles on Postgres/MySQL
- Some derived metrics are approximations and should be reviewed

---

## License

[Add your license here]