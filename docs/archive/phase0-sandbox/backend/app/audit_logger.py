"""
Audit logger for Phase 2, Phase 3 & Phase 4.
Writes each entry as a JSON line to a configured file, scoped by tenant_id.
Enforces action-only monitoring (claimed vs observed tools).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

from .config import BASE_DIR
from .tenant.isolation import tenant_audit_log_path

# Default audit log path; can be overridden via env var AUDIT_LOG_PATH
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", str(BASE_DIR / "data" / "audit.log"))

# Ensure directory exists
log_path = Path(AUDIT_LOG_PATH)
log_path.parent.mkdir(parents=True, exist_ok=True)

# Thread‑safe lock for concurrent writes
_lock = Lock()


def log_entry(entry: dict, tenant_id: str = "default") -> None:
    """Append a JSON‑encoded entry to the audit log.

    Ensures ``tenant_id`` is attached, and computes action-only monitoring
    fields (claimed_tools vs observed_tools) to detect mismatches.
    """
    entry["tenant_id"] = entry.get("tenant_id", tenant_id)

    # Compute claimed vs observed tools/metrics
    plan_info = entry.get("plan", {})
    synth_info = entry.get("synthesis", {})
    exec_info = entry.get("execution", {})

    claimed = synth_info.get("lineage") or [plan_info.get("metric_name") or plan_info.get("tool_name")]
    claimed = [str(c) for c in claimed if c]

    observed = []
    if "metric" in exec_info:
        observed.append(str(exec_info["metric"]))
    elif "tool" in exec_info:
        observed.append(str(exec_info["tool"]))
    elif exec_info.get("type"):
        observed.append(str(exec_info["type"]))

    entry["claimed_tools"] = entry.get("claimed_tools", claimed)
    entry["observed_tools"] = entry.get("observed_tools", observed)

    # Action-only monitoring: flag mismatch if claimed claims a tool not observed
    flags = entry.get("flags", [])
    if set(claimed) != set(observed) and observed:
        if "claim_observation_mismatch" not in flags:
            flags.append("claim_observation_mismatch")
    entry["flags"] = flags

    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        # Write to global audit log
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Write to tenant-isolated audit log
        t_path = tenant_audit_log_path(entry["tenant_id"])
        with open(t_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def get_recent(limit: int = 20, tenant_id: str | None = None) -> list[dict]:
    """Return up to *limit* recent audit entries, optionally filtered by *tenant_id*."""
    target_path = tenant_audit_log_path(tenant_id) if tenant_id else Path(AUDIT_LOG_PATH)

    if not target_path.exists():
        if tenant_id and os.path.exists(AUDIT_LOG_PATH):
            target_path = Path(AUDIT_LOG_PATH)
        else:
            return []

    with _lock:
        with open(target_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                item = json.loads(line)
                if tenant_id is None or item.get("tenant_id") == tenant_id:
                    entries.append(item)
                    if len(entries) >= limit:
                        break
            except Exception:
                pass
    return entries
