from backend.app.audit_logger import log_entry, get_recent


def test_action_monitoring_claimed_vs_observed(tmp_path, monkeypatch):
    test_log = tmp_path / "test_action_audit.log"
    monkeypatch.setattr("backend.app.audit_logger.AUDIT_LOG_PATH", str(test_log))

    entry_matching = {
        "question": "Total revenue",
        "plan": {"plan_type": "single_metric", "metric_name": "total_revenue"},
        "execution": {"metric": "total_revenue"},
        "synthesis": {"lineage": ["total_revenue"]},
    }
    log_entry(entry_matching, tenant_id="tenant_mon")

    entry_mismatch = {
        "question": "Total revenue",
        "plan": {"plan_type": "single_metric", "metric_name": "total_revenue"},
        "execution": {"metric": "order_count"},  # Mismatch!
        "synthesis": {"lineage": ["total_revenue"]},
    }
    log_entry(entry_mismatch, tenant_id="tenant_mon")

    recent = get_recent(limit=10, tenant_id="tenant_mon")
    assert len(recent) == 2

    # Newest item is entry_mismatch
    mismatch_item = recent[0]
    assert "claim_observation_mismatch" in mismatch_item["flags"]
