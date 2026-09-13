from backend.app.policy import PolicyCritic, get_policy_critic


def test_critic_non_evasion_blocked_retry():
    critic = PolicyCritic()
    tenant_id = "tenant_test_critic"

    # Register blocked target
    critic.register_denied_target(tenant_id, "forbidden_metric")

    plan_dict = {"plan_type": "single_metric", "metric_name": "forbidden_metric"}
    decision = critic.evaluate_plan("Show forbidden metric", plan_dict, None, tenant_id=tenant_id)

    assert decision.allow is False
    assert "blocked_action_retry" in decision.reason_codes
    assert decision.forced_confidence == "low"


def test_critic_allow_valid_metric():
    critic = PolicyCritic()
    plan_dict = {"plan_type": "single_metric", "metric_name": "total_revenue"}
    decision = critic.evaluate_plan("What is total revenue?", plan_dict, None, tenant_id="tenant_a")

    assert decision.allow is True
    assert decision.require_confirmation is False
    assert decision.reason_codes == []
