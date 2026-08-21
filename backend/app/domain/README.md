# Domain Layer

This directory is an **incremental** domain-split scaffold. The actual
implementation lives in the flat modules at `backend/app/` (e.g.
`agent_phase2.py`, `data_source.py`, `catalog/`, `tenant/`).

Each sub-package here re-exports the canonical implementation so callers can
import from a domain-oriented path without duplicating code:

- `domain/agent/`      → re-exports `agent_core`, `agent_phase2`
- `domain/catalog/`    → re-exports `catalog` package
- `domain/data/`       → re-exports `data_source`, `dataset_registry`, `data_layer`
- `domain/governance/` → re-exports `audit_logger`, `verification`, `pii_masker`, `resource_limits`
- `domain/tenant/`     → re-exports `tenant` package

The split is intentionally **not** a full rewrite — modules stay in place so
existing imports and tests keep working. Future refactors can move logic into
these sub-packages incrementally without breaking the public API.