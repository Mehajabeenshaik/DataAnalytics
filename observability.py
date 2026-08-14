"""
Structured observability for the governed agent.

Records per-request telemetry (plan type, latency, LLM calls, row counts,
errors) to a JSONL log per tenant. Admins can query this for usage and
troubleshooting.

Phase 2 of the DataAnalytics governed-agent roadmap.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR

_OBS_ROOT = Path(BASE_DIR) / "data" / "observability"
_lock = threading.Lock()


def _obs_path(tenant_id: str) -> Path:
    return _OBS_ROOT / f"{tenant_id}.jsonl"


def record_event(
    tenant_id: str,
    event_type: str,
    details: dict | None = None,
) -> None:
    """Append a structured telemetry event for a tenant.

    event_type examples: "ask", "plan", "execute", "synthesize", "error",
    "propose", "approve", "reject", "upload".
    """
    _OBS_ROOT.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "event_type": event_type,
        "details": details or {},
    }
    with _lock:
        with open(_obs_path(tenant_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def get_events(
    tenant_id: str,
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return recent telemetry events for a tenant (newest first)."""
    path = _obs_path(tenant_id)
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]
    return list(reversed(events[-limit:]))


def get_usage_summary(tenant_id: str, days: int = 30) -> dict:
    """Return a compact usage summary for a tenant over the last N days."""
    events = get_events(tenant_id, limit=10_000)
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    recent = [
        e for e in events
        if datetime.fromisoformat(e["timestamp"]).timestamp() >= cutoff
    ]
    by_type: dict[str, int] = {}
    for e in recent:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    return {
        "tenant_id": tenant_id,
        "days": days,
        "total_events": len(recent),
        "by_type": by_type,
    }