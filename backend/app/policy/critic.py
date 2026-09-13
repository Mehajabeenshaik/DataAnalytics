"""Verification Critic (Phase 4 policy) — the policy gate before execution.

Enforces:
  1. Allowlist — every planned metric/tool must exist for the tenant.
  2. Non-evasion — a denied target cannot be retried within the same session.
  3. Confirmation — consequential plan types must be approved before executing.
  4. Tool-availability honesty — execution failures force low confidence.

The critic is CODE, not a prompt: no amount of "please ignore the critic"
in a user question can bypass it because it runs outside the LLM.
"""

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
    """Central Verification Critic policy gate."""

    def __init__(self) -> None:
        # Per-tenant set of denied targets to enforce non-evasion.
        self._denied_targets: Dict[str, Set[str]] = {}

    def register_denied_target(self, tenant_id: str, target: str) -> None:
        if not target:
            return
        self._denied_targets.setdefault(tenant_id, set()).add(target.lower())

    # ── Allowlist helpers ────────────────────────────────────────────────

    def _plan_targets(self, plan_dict: Dict[str, Any]) -> List[str]:
        """Return every metric/tool target the plan would execute."""
        targets: List[str] = []
        metric_name = plan_dict.get("metric_name")
        if metric_name:
            targets.append(str(metric_name))
        tool_name = plan_dict.get("tool_name")
        if tool_name:
            targets.append(str(tool_name))
        for step in plan_dict.get("steps", []) or []:
            target = step.get("target")
            if target:
                targets.append(str(target))
        return targets

    def _catalog_allows(self, catalog: Any, target: str) -> bool:
        """Return True if `catalog` (a metrics dict or allowlist set) allows target."""
        if catalog is None:
            # No catalog provided -> allowlist check is skipped (defense in
            # depth elsewhere, e.g. execute_plan) but non-evasion still applies.
            return True
        # A set/frozenset: exact allowlist of names (metrics + tools).
        if isinstance(catalog, (set, frozenset)):
            return target in catalog
        # A metrics dict keyed by metric name.
        if isinstance(catalog, dict):
            return target in catalog
        # A catalog service-like object exposing allowed names.
        if hasattr(catalog, "tenants"):
            return target in catalog.tenants["default"].metrics
        return True

    # ── Pre-execution decision ───────────────────────────────────────────

    def evaluate_plan(
        self,
        question: str,
        plan_dict: Dict[str, Any],
        catalog: Any = None,
        tenant_id: str = "default",
    ) -> PolicyDecision:
        """Evaluate a plan BEFORE any metric/tool executes."""
        decision = PolicyDecision(allow=True)
        plan_type = plan_dict.get("plan_type")
        action = plan_dict.get("action", plan_type)

        targets = self._plan_targets(plan_dict)

        # 1. Non-evasion: previously denied targets may not be retried.
        denied = self._denied_targets.get(tenant_id, set())
        for target in targets:
            if target.lower() in denied:
                decision.allow = False
                decision.reason_codes.append("blocked_action_retry")
                decision.user_message = (
                    f"Action '{target}' was previously blocked for tenant '{tenant_id}' and cannot be retried."
                )
                decision.forced_confidence = "low"
                return decision

        # 2. Allowlist: every planned target must exist for the tenant.
        for target in targets:
            if not self._catalog_allows(catalog, target):
                decision.allow = False
                decision.reason_codes.append("target_not_allowed")
                decision.user_message = f"'{target}' is not in the tenant's approved metric/tool allowlist."
                decision.forced_confidence = "low"
                return decision

        # 3. Consequential actions require confirmation BEFORE execution.
        if plan_type in CONSEQUENTIAL_ACTIONS or action in CONSEQUENTIAL_ACTIONS:
            conf = get_confirmation_manager().create_request(
                tenant_id=tenant_id,
                question=question,
                action_type=plan_type or action,
                plan_details=plan_dict,
            )
            decision.require_confirmation = True
            decision.confirmation_token = conf.token
            decision.reason_codes.append("awaiting_confirmation")
            decision.user_message = f"Action '{plan_type}' requires explicit confirmation before it can run."
            return decision

        return decision
# ── Post-execution decision ──────────────────────────────────────────

    def evaluate_execution(self, exec_result: Any) -> PolicyDecision:
        """Evaluate execution output pre-synthesis (tool-availability honesty)."""
        decision = PolicyDecision(allow=True)

        if isinstance(exec_result, dict):
            if exec_result.get("type") in ("no_match", "error") or exec_result.get("error"):
                decision.reason_codes.append("tool_unavailable")
                decision.forced_confidence = "low"
                decision.user_message = exec_result.get("reason") or "Required tool or data source was unavailable."
        elif isinstance(exec_result, list):
            errored = [r for r in exec_result if isinstance(r, dict) and r.get("error")]
            if errored:
                decision.reason_codes.append("tool_unavailable")
                decision.forced_confidence = "low"
                decision.user_message = str(errored[0].get("error", "A step in the plan failed."))

        return decision


_global_critic = PolicyCritic()


def get_policy_critic() -> PolicyCritic:
    return _global_critic