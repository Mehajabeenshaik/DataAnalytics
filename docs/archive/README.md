# Archive

## phase0-sandbox

Historical sandbox only; not executed in production.

`phase0/` was an early standalone prototype. Its Phase 4 policy (critic,
confirmation, grounding, injection) was ported and enhanced into the single
production tree at `backend/app/policy/`, and the governed orchestrator lives
in `backend/app/agent_phase4.py`. Production runtime is exclusively `backend/`.