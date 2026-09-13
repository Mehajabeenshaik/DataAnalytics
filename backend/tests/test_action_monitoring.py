"""Action-monitoring audit tests — claimed vs observed tools/metrics (Phase 4).

Checks that record_action_audit() writes the claimed/observed fields and the
mismatch flag. We patch agent_phase4.log_action to capture the structured
details dict, keeping the test hermetic (no shared SQLite file).
"""

from unittest.mock import patch

from agent_phase4 import record_action_audit


def _captured_details(**kwargs):
    captured = {}

    def fake_log_action(username=None, role=None, action_type=None, details=None, **kw):
        captured["details"] = details

    with patch("agent_phase4.log_action", side_effect=fake_log_action):
        record_action_audit(**kwargs)
    return captured["details"]


def test_action_monitoring_matches_claimed_observed():
    det = _captured_details(
        tenant_id="tenant_mon",
        user="system",
        plan_type="single_metric",
        claimed=["total_revenue"],
        observed=["total_revenue"],
        confidence="high",
        flags=[],
        reason_codes=[],
        question_preview="What is total revenue?",
    )
    assert det["claim_observation_mismatch"] is False
    assert "claim_observation_mismatch" not in det["flags"]


def test_action_monitoring_detects_mismatch():
    det = _captured_details(
        tenant_id="tenant_mon",
        user="system",
        plan_type="single_metric",
        claimed=["total_revenue"],
        observed=["order_count"],
        confidence="low",
        flags=[],
        reason_codes=[],
        question_preview="What is total revenue?",
    )
    assert det["claim_observation_mismatch"] is True
    assert "claim_observation_mismatch" in det["flags"]


def test_audit_gets_claimed_observed_fields():
    det = _captured_details(
        tenant_id="tenant_mon",
        user="system",
        plan_type="stats_tool",
        claimed=["describe"],
        observed=["describe"],
        confidence="high",
        flags=[],
        reason_codes=[],
        question_preview="describe the data",
    )
    assert det["claimed_tools_metrics"] == ["describe"]
    assert det["observed_tools_metrics"] == ["describe"]
    assert det["tenant_id"] == "tenant_mon"
    assert det["plan_type"] == "stats_tool"