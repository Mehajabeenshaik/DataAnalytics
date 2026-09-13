"""Production Phase 4 orchestrator — governed agentic policy.

This is the canonical governed ask path for the production runtime
(backend/app/). Unlike the legacy ask() loop, policy is enforced BEFORE
execution by the Verification Critic, not retro-fitted afterwards.

Mandatory order (see P2.2):
  1. Tenant + quota (existing)                      — scope + budget
  2. Sanitize question (injection resistance)       — data never becomes instructions
  3. Plan (deterministic + LLM, allowlist only)     — planner selects from catalog
  4. pre_execution_critic                           — deny / require_confirmation
  5. Execute deterministic metrics/tools             — ONLY if allow + not awaiting
  6. PII scrub (defense-in-depth)                   — LLM sees scrubbed results only
  7. post_execution_critic + verification           — tool-availability honesty
  8. Synthesize (LLM)                               — over scrubbed results
  9. Grounding check                                — never overstate what a tool did
 10. Audit (claimed vs observed tools/metrics)      — action monitoring
 11. Return answer, confidence, flags, lineage, invariant

The core invariant is preserved: the LLM never generates or executes SQL or
Python. It only selects from the approved catalog; execution is deterministic
and fully governed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from data_source import DataSource
from llm_provider import LLMProvider
from agent_phase2 import (
    Plan,
    _resolve_question,
    execute_plan,
    synthesize,
    _json_safe,
    get_memory,
)
from verification import verify_answer
from chart_builder import build_chart_spec
from resource_limits import apply_row_limit, run_with_timeout, max_plan_steps
from tenant_quotas import check_and_consume_query_quota
from audit_logger import log_action
from stats_tools import VALID_TOOL_NAMES
from model_tools import VALID_MODEL_TOOL_NAMES
from policy import (
    get_policy_critic,
    check_grounding,
    attach_lineage,
    sanitise_request,
)

INVARIANT = "The LLM never generates or executes SQL or Python."


def _allowlist(metrics: Dict[str, Any]) -> set:
    """Combined tenant allowlist: approved metric names + governed tool names."""
    return set(metrics.keys()) | set(VALID_TOOL_NAMES) | set(VALID_MODEL_TOOL_NAMES)


def _observed_targets(results: List[dict]) -> List[str]:
    """Distinct tool/metric targets actually executed (no PII)."""
    seen: List[str] = []
    for r in results:
        t = r.get("target")
        if t and t not in seen:
            seen.append(t)
    return seen


def record_action_audit(
    tenant_id: str,
    user: str,
    plan_type: str,
    claimed: List[str],
    observed: List[str],
    confidence: str,
    flags: List[str],
    reason_codes: List[str],
    question_preview: str,
) -> None:
    """Write an action-monitoring audit entry (claimed vs observed)."""
    claim_obs = sorted(set(claimed)) != sorted(set(observed))
    all_flags = list(dict.fromkeys([*flags, *reason_codes]))
    if claim_obs and "claim_observation_mismatch" not in all_flags:
        all_flags.append("claim_observation_mismatch")

    details = {
        "tenant_id": tenant_id,
        "plan_type": plan_type,
        "claimed_tools_metrics": claimed,
        "observed_tools_metrics": observed,
        "confidence": confidence,
        "flags": all_flags,
        "reason_codes": reason_codes,
        "claim_observation_mismatch": claim_obs,
        "question_preview": question_preview[:80],
    }
    try:
        log_action(
            username=user,
            role="agent",
            action_type="QUERY",
            details=details,
            tenant_id=tenant_id,
        )
    except Exception:  # audit must never crash the request
        pass


def _governed_early_response(early_response: dict, status: str) -> dict:
    """Normalize an early (no-execution) response from _resolve_question."""
    return {
        **early_response,
        "status": status,
        "flags": early_response.get("flags", []),
        "invariant": INVARIANT,
        "policy": {"phase": 4, "enforced": True},
    }


def run_governed_ask(
    question: str,
    ds: DataSource,
    provider: LLMProvider,
    tenant_id: str = "default",
    user: str = "system",
    dataset_names: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> dict:
    """Execute a question under Phase 4 governed safety policies (see above)."""
    critic = get_policy_critic()
    execution_phase = "unknown"
    confidence = "n/a"
    claimed: List[str] = []
    observed: List[str] = []

    # 1. Tenant + quota (existing boundary). `default` is the local demo tenant.
    if tenant_id and tenant_id != "default":
        check_and_consume_query_quota(tenant_id)

    # 2. Injection resistance: sanitize the question up front so the planner
    #    never sees instruction-like payloads as control-flow directives.
    clean_question = sanitise_request(question)

    prior_context = get_memory().get_context(session_id) if session_id else ""

    try:
        # 3. Plan (deterministic fallbacks + LLM, allowlist only).
        the_plan, early_response = _resolve_question(
            clean_question,
            ds,
            provider,
            tenant_id=tenant_id,
            dataset_names=dataset_names,
            prior_context=prior_context,
        )
        plan_type = the_plan.plan_type if the_plan else "early"

        if early_response is not None:
            status = "completed"
            # propose_metric already gates on human approval (no side effect runs).
            if early_response.get("proposal_status") == "pending":
                status = "awaiting_approval"
            confidence = early_response.get("confidence", "n/a")
            claimed = early_response.get("lineage", {}).get("metrics_or_tools_used", [])
            observed = claimed
            record_action_audit(
                tenant_id=tenant_id,
                user=user,
                plan_type=plan_type,
                claimed=claimed,
                observed=observed,
                confidence=confidence,
                flags=[],
                reason_codes=early_response.get("caveats", []),
                question_preview=clean_question,
            )
            return _governed_early_response(early_response, status)

        # Cap plan steps to tenant/global limit.
        the_plan.steps = the_plan.steps[: max_plan_steps()]
        plan_dict = the_plan.model_dump()
        claimed = [s.target for s in the_plan.steps if s.target]

        # 4. Pre-execution critic: policy gate BEFORE any execution.
        pre = critic.evaluate_plan(
            clean_question, plan_dict, _allowlist(ds.get_metrics()), tenant_id=tenant_id
        )
        execution_phase = plan_type

        if pre.require_confirmation:
            return {
                "status": "awaiting_confirmation",
                "tenant_id": tenant_id,
                "question": clean_question,
                "confirmation_token": pre.confirmation_token,
                "user_message": pre.user_message,
                "plan": plan_dict,
                "plan_type": plan_type,
                "flags": pre.reason_codes,
                "confidence": "n/a",
                "claimed_tools_metrics": claimed,
                "observed_tools_metrics": [],
                "policy": {"phase": 4, "enforced": True, "decision": "awaiting_confirmation"},
                "invariant": INVARIANT,
            }

        if not pre.allow:
            for target in claimed:
                critic.register_denied_target(tenant_id, target)
            confidence = pre.forced_confidence or "low"
            record_action_audit(
                tenant_id=tenant_id,
                user=user,
                plan_type=plan_type,
                claimed=claimed,
                observed=[],
                confidence=confidence,
                flags=pre.reason_codes,
                reason_codes=pre.reason_codes,
                question_preview=clean_question,
            )
            return {
                "status": "rejected",
                "tenant_id": tenant_id,
                "question": clean_question,
                "plan": plan_dict,
                "plan_type": plan_type,
                "confidence": confidence,
                "flags": pre.reason_codes,
                "user_message": pre.user_message,
                "claimed_tools_metrics": claimed,
                "observed_tools_metrics": [],
                "policy": {"phase": 4, "enforced": True, "decision": "rejected"},
                "invariant": INVARIANT,
            }

        # 5. Execute deterministic metrics/tools (with row limits + timeouts).
        def _execute() -> List[dict]:
            results = execute_plan(the_plan, ds)
            for r in results:
                if r.get("result") is not None and not r.get("error"):
                    r["result"] = apply_row_limit(r["result"])
                    if hasattr(r["result"], "attrs") and r["result"].attrs.get("truncated"):
                        r["_truncated"] = True
            return results

        results = run_with_timeout(_execute)
        observed = _observed_targets(results)
# 7a. Post-execution critic (tool-availability honesty).
        post = critic.evaluate_execution(results)

        # 6/8. Synthesize — _build_synthesize_prompt scrubs PII from results,
        #      so the LLM only ever sees scrubbed data.
        answer = synthesize(clean_question, the_plan, results, provider)
        answer.pop("_parse_failed", None)

        # 7b. Verification — deterministic, computed (LLM self-report ignored).
        verification = verify_answer(the_plan, results, answer, question=clean_question)
        computed_confidence = verification["computed_confidence"]

        # 9. Grounding check — neutralize narrative overclaims.
        ground = check_grounding(answer.get("answer", ""), results)
        if not ground["grounded"]:
            answer["answer"] = ground["sanitized_answer"]

        flags = list(
            dict.fromkeys(
                [
                    *verification["flags"],
                    *pre.reason_codes,
                    *post.reason_codes,
                    *ground["flags"],
                ]
            )
        )
        confidence = post.forced_confidence or pre.forced_confidence or computed_confidence

        # Lineage (grounded to what actually executed).
        lineage_payload = attach_lineage(answer.get("answer", ""), observed)
        lineage = {
            "metrics_or_tools_used": lineage_payload["lineage"] or claimed,
            "filters_applied": {},
            "notes": "Phase 4 governed pipeline; deterministic execution; system-computed confidence.",
        }

        # Chart (already-computed, already-verified results; no new computation).
        chart = None
        if plan_type not in ("no_match", "propose_metric"):
            for r in reversed(results):
                chart = build_chart_spec(r)
                if chart:
                    break

        # Memory (prior-turn context only; never affects allowlist).
        if session_id and plan_type not in ("no_match", "propose_metric"):
            primary = next(
                (s for s in the_plan.steps if s.action in ("run_metric", "run_stats", "run_model")),
                None,
            )
            get_memory().record_turn(
                session_id=session_id,
                question=clean_question,
                plan_type=plan_type,
                target=getattr(primary, "target", None),
                filters=getattr(primary, "filters", None),
                groupby=(primary.args or {}).get("group_col") if primary else None,
            )

        # 10. Audit — claimed vs observed, plus all policy flags.
        record_action_audit(
            tenant_id=tenant_id,
            user=user,
            plan_type=plan_type,
            claimed=claimed,
            observed=observed,
            confidence=confidence,
            flags=flags,
            reason_codes=[*pre.reason_codes, *post.reason_codes],
            question_preview=clean_question,
        )

        claim_obs_mismatch = sorted(set(claimed)) != sorted(set(observed))
        response = {
            **answer,
            "status": "completed",
            "tenant_id": tenant_id,
            "plan": plan_dict,
            "plan_type": plan_type,
            "results": results,
            "confidence": confidence,
            "flags": flags,
            "claim_observation_mismatch": claim_obs_mismatch,
            "claimed_tools_metrics": claimed,
            "observed_tools_metrics": observed,
            "lineage": lineage,
            "verification": verification,
            "policy": {"phase": 4, "enforced": True, "decision": "allowed"},
            "invariant": INVARIANT,
        }
        if chart:
            response["chart"] = chart
        return _json_safe(response)

    except Exception as e:
        execution_phase = execution_phase or "unknown"
        record_action_audit(
            tenant_id=tenant_id,
            user=user,
            plan_type=execution_phase,
            claimed=claimed,
            observed=observed,
            confidence="low",
            flags=["execution_error"],
            reason_codes=[type(e).__name__],
            question_preview=clean_question,
        )
        raise