# Phase 4 — Agentic Policy & Astra Safety Patterns

## Overview
Phase 4 embeds frontier agentic safety patterns (inspired by system cards such as GPT-6 Astra) into hard code policy gates — not soft prompts that an LLM can bypass or hallucinate around.

---

## The Core Agentic Safety Patterns

### 1. Consequential Action Confirmation (`backend/app/policy/confirmation.py`)
Consequential actions (`export_external`, `write_back`, `send_report`, `propose_metric`) pause execution and return status `"awaiting_confirmation"` with a unique token. The client must invoke `POST /ask/confirm` with `{"confirmation_token": "...", "approve": true}` to finalize.

### 2. Blocked-Action Non-Evasion (`backend/app/policy/critic.py`)
If a metric or tool action is denied or blocked, the critic registers the target. Attempts by the planner to retry rephrased or equivalent versions of the blocked action are denied immediately with reason code `blocked_action_retry`.

### 3. Grounding & Honest Claims (`backend/app/policy/grounding.py`)
Structural checks verify narrative claims against observed tool results. Claims like *"I verified with the database"* without supporting tool results trigger reason code `ungrounded_claim` and forced low confidence.

### 4. Tool & Data Availability Honesty (`backend/app/policy/critic.py`)
On timeout, missing metric, or database failure, the agent explicitly states the unavailability instead of degrading into a plausible best-effort guess. Sets flag `tool_unavailable` and forced low confidence.

### 5. Data-as-Data / Prompt-Injection Resistance (`backend/app/policy/injection.py`)
All ingested CSV cell contents, schema profiles, and user inputs are passed through `sanitize_data_content()` to neutralize instruction override strings (e.g. *"ignore previous instructions"*).

### 6. Action-Only Monitoring (`backend/app/audit_logger.py`)
Audit entries record both `claimed_tools` (from synthesis/plan) and `observed_tools` (from execution). Any discrepancy automatically triggers flag `claim_observation_mismatch`.

---

## API Usage Examples

### Consequential Action & Confirmation Flow
```bash
# 1. Ask question that triggers consequential action
curl -s -X POST http://127.0.0.1:8001/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: key_tenant_a_123" \
  -d '{"question": "Propose a new metric for customer churn"}'
# Returns: {"status": "awaiting_confirmation", "confirmation_token": "confirm_123..."}

# 2. Confirm action
curl -s -X POST http://127.0.0.1:8001/ask/confirm \
  -H "Content-Type: application/json" \
  -H "X-API-Key: key_tenant_a_123" \
  -d '{"confirmation_token": "confirm_123...", "approve": true}'
```
