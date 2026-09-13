# backend/app/agent_phase4.py
"""
Phase 4 Orchestrator — Agentic Policy & Astra Patterns.

Integrates:
1. Multi-tenancy & Quota governance (Phase 3)
2. Prompt injection resistance & data-as-data (Phase 4)
3. Verification Critic (Allowlist, Non-evasion, Availability, Confirmation) (Phase 4)
4. Deterministic Execution & PII Masking (Phase 0-2)
5. Grounding check & Action-Only Audit monitoring (Phase 4)
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from .agent_phase1 import plan, execute, synthesize
from .verification import verify_answer
from .audit_logger import log_entry
from .policy import get_policy_critic, check_grounding, sanitize_data_content


def run_question_phase4(
    question: str, ds: Any, catalog: Any, tenant_id: str = "default"
) -> Dict[str, Any]:
    """Execute a question under Phase 4 agentic safety policies."""
    critic = get_policy_critic()

    # 1. Injection resistance: sanitize input question
    clean_question = sanitize_data_content(question)

    # 2. Plan generation (LLM allowlist selection only)
    plan_obj = plan(clean_question, ds, catalog, tenant_id=tenant_id)
    plan_dict = plan_obj.model_dump() if hasattr(plan_obj, "model_dump") else plan_obj.dict()

    # 3. Pre-Execution Critic evaluation
    pre_decision = critic.evaluate_plan(clean_question, plan_dict, catalog, tenant_id=tenant_id)

    # Hand off to confirmation flow if action is consequential
    if pre_decision.require_confirmation:
        return {
            "status": "awaiting_confirmation",
            "tenant_id": tenant_id,
            "question": clean_question,
            "confirmation_token": pre_decision.confirmation_token,
            "user_message": pre_decision.user_message,
            "plan": plan_dict,
            "invariant": "The LLM never generates or executes SQL or Python.",
        }

    # Handle denied plan (e.g. blocked action non-evasion retry)
    if not pre_decision.allow:
        critic.register_denied_target(
            tenant_id, plan_dict.get("metric_name") or plan_dict.get("tool_name") or "unknown"
        )
        return {
            "status": "rejected",
            "tenant_id": tenant_id,
            "question": clean_question,
            "plan": plan_dict,
            "confidence": pre_decision.forced_confidence or "low",
            "flags": pre_decision.reason_codes,
            "user_message": pre_decision.user_message,
            "invariant": "The LLM never generates or executes SQL or Python.",
        }

    # 4. Deterministic Execution
    exec_result = execute(plan_obj, ds, catalog, tenant_id=tenant_id)

    # 5. Post-Execution Critic evaluation (tool availability honesty)
    post_decision = critic.evaluate_execution(exec_result)

    # 6. Synthesis generation
    synthesis = synthesize(clean_question, exec_result)

    # 7. Grounding check on narrative synthesis
    ground_res = check_grounding(synthesis.get("answer", ""), exec_result)
    if not ground_res["grounded"]:
        synthesis["answer"] = ground_res["sanitized_answer"]

    # 8. Post-hoc Verification
    verification = verify_answer(
        plan=plan_dict,
        results=exec_result,
        synthesized=synthesis,
        question=clean_question,
    )

    # Combine flags from critic, grounding, and verification
    combined_flags = list(
        set(
            verification.get("flags", [])
            + pre_decision.reason_codes
            + post_decision.reason_codes
            + ground_res.get("flags", [])
        )
    )

    forced_confidence = (
        post_decision.forced_confidence or pre_decision.forced_confidence or verification["confidence"]
    )

    # Construct final response object
    response = {
        "status": "completed",
        "question": clean_question,
        "tenant_id": tenant_id,
        "plan": plan_dict,
        "execution": exec_result,
        "synthesis": synthesis,
        "verification": verification,
        "confidence": forced_confidence,
        "flags": combined_flags,
        "lineage": synthesis.get("lineage") or [plan_dict.get("metric_name") or plan_dict.get("tool_name") or "catalog"],
        "invariant": "The LLM never generates or executes SQL or Python.",
    }

    # 9. Action-Only Audit log
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "question": clean_question,
        "plan": plan_dict,
        "execution": exec_result,
        "synthesis": synthesis,
        "verification": verification,
        "confidence": forced_confidence,
        "flags": combined_flags,
    }
    try:
        log_entry(entry, tenant_id=tenant_id)
    except Exception as e:
        import logging
        logging.getLogger("daana.audit").warning("Failed to write audit entry: %s", e)

    return response
