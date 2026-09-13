from __future__ import annotations

from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from .confirmation import get_confirmation_manager, CONSEQUENTIAL_ACTIONS


class PolicyDecision(BaseModel):
    allow: bool = True
    require_confirmation: bool = False
    confirmation_token: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)
    user_message: Optional[str] = None
    forced_confidence: Optional[str] = None


class PolicyCritic:
    """Central Verification Critic policy gate.

    Enforces Astra-style systems safety:
    1. Allowlist enforcement & Non-evasion (blocked target retry prevention)
    2. Confirmation requirement for consequential actions
    3. Tool availability honesty
    """

    def __init__(self) -> None:
        # Per-tenant session set of denied targets to enforce non-evasion
        self._denied_targets: Dict[str, Set[str]] = {}

    def register_denied_target(self, tenant_id: str, target: str) -> None:
        """Register a denied metric/tool target for non-evasion tracking."""
        if tenant_id not in self._denied_targets:
            self._denied_targets[tenant_id] = set()
        self._denied_targets[tenant_id].add(target.lower())

    def evaluate_plan(
        self, question: str, plan_dict: Dict[str, Any], catalog: Any, tenant_id: str = "default"
    ) -> PolicyDecision:
        """Evaluate plan pre-execution."""
        decision = PolicyDecision(allow=True)
        plan_type = plan_dict.get("plan_type")

        # 1. Non-evasion check: blocked target retry
        target_name = plan_dict.get("metric_name") or plan_dict.get("tool_name")
        if target_name:
            denied_set = self._denied_targets.get(tenant_id, set())
            if target_name.lower() in denied_set:
                decision.allow = False
                decision.reason_codes.append("blocked_action_retry")
                decision.user_message = (
                    f"Action '{target_name}' was previously blocked for tenant '{tenant_id}' and cannot be retried."
                )
                decision.forced_confidence = "low"
                return decision

        # 2. Consequential action check
        conf_manager = get_confirmation_manager()
        if plan_type in CONSEQUENTIAL_ACTIONS:
            req = conf_manager.create_request(
                tenant_id=tenant_id,
                question=question,
                action_type=plan_type,
                plan_details=plan_dict,
            )
            decision.require_confirmation = True
            decision.confirmation_token = req.token
            decision.reason_codes.append("awaiting_confirmation")
            decision.user_message = f"Action '{plan_type}' requires explicit confirmation."
            return decision

        return decision

    def evaluate_execution(self, exec_result: Dict[str, Any]) -> PolicyDecision:
        """Evaluate execution output pre-synthesis."""
        decision = PolicyDecision(allow=True)

        # Tool availability check
        if exec_result.get("type") in ("no_match", "error") or "error" in exec_result:
            decision.reason_codes.append("tool_unavailable")
            decision.forced_confidence = "low"
            decision.user_message = exec_result.get("reason") or "Required tool or data source was unavailable."

        return decision


_global_critic = PolicyCritic()


def get_policy_critic() -> PolicyCritic:
    return _global_critic
