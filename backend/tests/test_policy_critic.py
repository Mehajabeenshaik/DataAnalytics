"""PolicyCritic unit tests — allowlist, non-evasion, confirmation, availability.

These exercise the Phase 4 policy gate directly (code, not prompts).
"""

from policy.critic import PolicyCritic
from policy import get_confirmation_manager, CONSEQUENTIAL_ACTIONS
from config import _DEMO_API_KEY_SENTINEL  # noqa: F401  (ensures config loads)


def _plan(plan_type: str = "single_metric", steps=None, metric_name=None, tool_name=None):
    plan = {
        "plan_type": plan_type,
        "can_answer": True,
        "reason": "test",
        "steps": steps or [{"step_id": 1, "action": "run_metric", "target": "total_revenue", "filters": {}, "args": {}}],
    }
    if metric_name:
        plan["metric_name"] = metric_name
    if tool_name:
        plan["tool_name"] = tool_name
    return plan


def test_critic_non_evasion_blocked_retry():
    critic = PolicyCritic()
    tenant_id = "tenant_test_critic"
    critic.register_denied_target(tenant_id, "forbidden_metric")
    decision = critic.evaluate_plan(
        "Show forbidden metric", _plan(metric_name="forbidden_metric"), None, tenant_id=tenant_id
    )
    assert decision.allow is False
    assert "blocked_action_retry" in decision.reason_codes
    assert decision.forced_confidence == "low"


def test_critic_allow_valid_metric():
    critic = PolicyCritic()
    catalog = {"total_revenue": {"agg": "sum"}}
    decision = critic.evaluate_plan(
        "What is total revenue?",
        _plan(metric_name="total_revenue"),
        catalog,
        tenant_id="tenant_a",
    )
    assert decision.allow is True
    assert decision.require_confirmation is False
    assert decision.reason_codes == []


def test_critic_allowlist_rejects_unknown_metric():
    critic = PolicyCritic()
    catalog = {"total_revenue": {"agg": "sum"}}
    decision = critic.evaluate_plan(
        "Invented metric",
        _plan(metric_name="invented_metric"),
        catalog,
        tenant_id="tenant_a",
    )
    assert decision.allow is False
    assert "target_not_allowed" in decision.reason_codes
    assert decision.forced_confidence == "low"


def test_critic_consequential_requires_confirmation():
    critic = PolicyCritic()
    decision = critic.evaluate_plan(
        "Export this", _plan(plan_type="export_external", tool_name="exporter"), None, tenant_id="tenant_a"
    )
    assert decision.allow is True
    assert decision.require_confirmation is True
    assert decision.confirmation_token is not None
    assert "awaiting_confirmation" in decision.reason_codes


def test_read_only_plan_does_not_require_confirmation():
    critic = PolicyCritic()
    decision = critic.evaluate_plan(
        "What is revenue?", _plan(plan_type="single_metric", metric_name="total_revenue"), None, tenant_id="tenant_a"
    )
    assert decision.require_confirmation is False


def test_critic_availability_honesty_on_error():
    critic = PolicyCritic()
    decision = critic.evaluate_execution({"type": "no_match", "reason": "No such tool"})
    assert "tool_unavailable" in decision.reason_codes
    assert decision.forced_confidence == "low"


def test_critic_availability_honesty_on_step_error():
    critic = PolicyCritic()
    decision = critic.evaluate_execution([{"target": "total_revenue", "error": "boom"}])
    assert "tool_unavailable" in decision.reason_codes
    assert decision.forced_confidence == "low"


def test_confirmation_consequential_set_is_complete():
    for action in ("export_external", "write_back", "send_report", "propose_metric"):
        assert action in CONSEQUENTIAL_ACTIONS


def test_confirmation_manager_roundtrip():
    mgr = get_confirmation_manager()
    req = mgr.create_request("tenant_a", "Export now", "export_external", {"a": 1})
    assert req.token.startswith("confirm_")
    assert req.status == "pending"
    pending = mgr.get_pending(req.token)
    assert pending is not None
    resolved = mgr.resolve(req.token, approve=True)
    assert resolved.status == "approved"
    # Once resolved, the token is gone.
    assert mgr.get_pending(req.token) is None


def test_confirmation_manager_ttl_expiry():
    mgr = get_confirmation_manager()
    req = mgr.create_request("tenant_a", "Export now", "export_external", {}, ttl_seconds=-1)
    assert mgr.get_pending(req.token) is None