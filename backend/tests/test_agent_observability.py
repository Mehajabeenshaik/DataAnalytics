"""Integration test: ask() records audit + observability when enabled."""

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_source import DataSource
from agent_phase2 import ask


@pytest.fixture
def ds():
    df = pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5, 6],
            "revenue": [100.0, 200.0, 300.0, 150.0, 250.0, 400.0],
            "region": ["North", "South", "North", "East", "West", "South"],
        }
    )
    d = DataSource()
    d.load_dataframe(df)
    return d


@pytest.fixture
def provider():
    p = MagicMock()
    # First call = planner, second call = synthesizer
    p.generate.side_effect = [
        json.dumps({
            "can_answer": True,
            "reason": "Found metric",
            "plan_type": "single_metric",
            "steps": [
                {"step_id": 1, "action": "run_metric", "target": "total_revenue", "filters": {}, "args": {}}
            ],
        }),
        json.dumps({
            "answer": "Total revenue is 1400.",
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": ["total_revenue"], "filters_applied": {}, "notes": "6 rows"},
        }),
    ]
    return p


def test_ask_records_observability_and_audit(ds, provider, tmp_path, monkeypatch):
    """ask() with a real tenant_id writes an observability line + audit entry."""
    import observability

    # Point observability at a temp dir so we can inspect it.
    monkeypatch.setattr(observability, "_OBS_ROOT", tmp_path / "obs")

    # Run the agent under a non-default tenant (quota path active).
    result = ask(
        "What is total revenue?",
        ds,
        provider,
        tenant_id="tenant_integration",
        user="tester",
    )

    assert result["confidence"] == "high"
    assert "total_revenue" in result.get("lineage", {}).get("metrics_or_tools_used", [])

    # 1. Observability log line exists (no PII in it).
    obs_events = observability.get_events("tenant_integration", event_type="agent_run")
    assert len(obs_events) == 1
    details = obs_events[0]["details"]
    assert details["plan_type"] in ("single_metric", "stats_tool", "multi_step")
    assert details["confidence"] == "high"
    assert "total_revenue" in details["metrics_or_tools"]
    assert all(k not in json.dumps(details) for k in ("customer", "password", "secret"))

    # 2. Tenant-scoped audit entry exists (written to the default audit DB).
    from audit_logger import get_audit_logs

    rows = get_audit_logs(tenant_id="tenant_integration", db_path="audit.db")
    assert any(r["action_type"] == "QUERY" for r in rows)
    # The audit detail must NOT contain the full question text beyond the preview.
    for r in rows:
        if r["action_type"] == "QUERY" and r.get("details"):
            assert "question_preview" in r["details"]
            assert len(r["details"].get("question_preview", "")) <= 80

    # 3. Quota counter was consumed.
    from tenant_quotas import get_usage

    usage = get_usage("tenant_integration")
    assert usage["queries"] >= 1