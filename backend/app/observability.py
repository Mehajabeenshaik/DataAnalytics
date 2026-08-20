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


# ── Agent-run telemetry (Phase 2.5) ───────────────────────────────────────

def log_agent_run(
    tenant_id: str,
    plan_type: str,
    metrics_or_tools: list[str] | None = None,
    latency_ms: int = 0,
    confidence: str = "n/a",
    error: str | None = None,
) -> None:
    """Record a single agent ask() run as a structured telemetry event.

    No PII is ever written here — only plan_type, metric/tool names,
    latency, confidence, and error type.
    """
    record_event(
        tenant_id,
        "agent_run",
        {
            "plan_type": plan_type,
            "metrics_or_tools": metrics_or_tools or [],
            "latency_ms": latency_ms,
            "confidence": confidence,
            "error": error,
        },
    )


def counters(tenant_id: str) -> dict:
    """Return lightweight in-memory counters for a tenant (for tests/UI).

    Reads the JSONL log and counts agent_run events by outcome.
    """
    events = get_events(tenant_id, event_type="agent_run", limit=10_000)
    total = len(events)
    errors = sum(1 for e in events if e.get("details", {}).get("error"))
    return {
        "tenant_id": tenant_id,
        "total_runs": total,
        "errors": errors,
        "successes": total - errors,
    }
