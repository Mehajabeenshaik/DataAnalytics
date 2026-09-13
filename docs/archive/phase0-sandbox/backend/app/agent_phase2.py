# backend/app/agent_phase2.py
"""
Phase 2 & Phase 3 orchestrator.
Wraps the Phase 1 run_question, adds deterministic verification, system‑computed confidence,
and tenant-scoped audit logging.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict

from .agent_phase1 import run_question
from .verification import verify_answer
from .audit_logger import log_entry


def run_question_phase2(question: str, ds: Any, catalog: Any, tenant_id: str = "default") -> Dict[str, Any]:
    """Execute a user question with safety verification for a specific tenant.

    Returns the original Phase 1 response plus top-level system confidence,
    flags, lineage, invariant, and verification details. The whole interaction
    is logged to the tenant's audit log.
    """
    # Phase 1 execution with tenant scoping
    response = run_question(question, ds, catalog, tenant_id=tenant_id)

    # Deterministic verification of the tool result and synthesizer output
    verification = verify_answer(
        plan=response.get("plan", {}),
        results=response.get("execution", {}),
        synthesized=response.get("synthesis", {}),
        question=question,
    )

    # Attach verification and top-level safety fields
    response["verification"] = verification
    response["confidence"] = verification["confidence"]
    response["flags"] = verification["flags"]
    response["tenant_id"] = tenant_id

    if "lineage" not in response:
        synth_lineage = response.get("synthesis", {}).get("lineage")
        if synth_lineage:
            response["lineage"] = synth_lineage
        elif "lineage" in response.get("execution", {}):
            response["lineage"] = response["execution"]["lineage"]
        else:
            plan_info = response.get("plan", {})
            metric_or_tool = plan_info.get("metric_name") or plan_info.get("tool_name") or "catalog"
            response["lineage"] = [metric_or_tool]

    # Audit log entry with tenant_id
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "question": question,
        "plan": response.get("plan"),
        "execution": response.get("execution"),
        "synthesis": response.get("synthesis"),
        "verification": verification,
        "confidence": verification["confidence"],
        "flags": verification["flags"],
    }
    try:
        log_entry(entry, tenant_id=tenant_id)
    except Exception as e:
        import logging
        logging.getLogger("daana.audit").warning("Failed to write audit entry: %s", e)

    return response
