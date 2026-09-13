# backend/app/verification.py
"""
Verification utilities for Phase 2.

The core function ``verify_answer`` inspects the deterministic execution
results and the synthesis metadata (if any) to compute a system confidence
level and a list of flags.

It never calls an LLM – all checks are pure Python.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
import math


def _is_numeric_series(series) -> bool:
    """Return True if a pandas Series looks numeric (int/float)."""
    try:
        import pandas as pd
    except ImportError:
        return False
    return pd.api.types.is_numeric_dtype(series)


def verify_answer(
    plan: Dict[str, Any],
    results: Dict[str, Any],
    synthesized: Dict[str, Any] | None = None,
    question: Optional[str] = None,
) -> Dict[str, Any]:
    """Deterministic post‑hoc verification.

    Parameters
    ----------
    plan:
        The validated plan dictionary produced by the planner.
    results:
        The deterministic tool execution dictionary (output of ``execute``).
    synthesized:
        The JSON object returned by the synthesizer LLM (may be ``None`` if the
        LLM failed to produce a parsable JSON).  The function does **not** trust
        any ``confidence`` field inside this object.
    question:
        Optional original user question – currently unused but kept for API
        stability.

    Returns
    -------
    dict with keys ``ok``, ``confidence``, ``flags`` and ``messages``.
    """
    flags: List[str] = []
    messages: List[str] = []
    ok = True

    # ------------------------------------------------------------------
    # Helper: safe get of row count from the DataSource profile (if available)
    # ------------------------------------------------------------------
    source_row_count = None
    if "_source_profile" in results:
        source_row_count = results["_source_profile"].get("n_rows")

    # ------------------------------------------------------------------
    # 1. Row‑count sanity (only for tools that claim a count)
    # ------------------------------------------------------------------
    if "row_count" in results:
        rc = results["row_count"]
        if source_row_count is not None and rc > source_row_count:
            ok = False
            flags.append("row_overflow")
            messages.append(
                f"Result row count {rc} exceeds source rows {source_row_count}."
            )

    # ------------------------------------------------------------------
    # 2. Non‑negative checks for money‑like or quantity fields (heuristic)
    # ------------------------------------------------------------------
    for key, value in results.items():
        if isinstance(value, (int, float)) and ("amount" in str(key).lower() or "revenue" in str(key).lower() or "count" in str(key).lower()):
            if value < 0:
                ok = False
                flags.append("negative_value")
                messages.append(f"Field {key} has negative value {value}.")

    # ------------------------------------------------------------------
    # 3. Breakdown consistency – if a total and a breakdown are present
    # ------------------------------------------------------------------
    if "breakdown" in results and "total" in results:
        total = results["total"]
        breakdown_sum = sum(item.get("value", 0) for item in results["breakdown"])
        if not math.isclose(total, breakdown_sum, rel_tol=1e-3):
            ok = False
            flags.append("breakdown_mismatch")
            messages.append(
                f"Breakdown sum {breakdown_sum:.2f} differs from total {total:.2f}."
            )

    # ------------------------------------------------------------------
    # 4. Truncation detection – many tools (e.g., value_counts) may return a
    #    ``truncated`` boolean flag; if missing, we assume not truncated.
    # ------------------------------------------------------------------
    truncated = results.get("truncated", False)
    if truncated:
        flags.append("truncated")
        messages.append("Result set was truncated.")

    # ------------------------------------------------------------------
    # 5. Synthesizer parse failure – caller may pass ``synthesized=None``
    # ------------------------------------------------------------------
    if synthesized is None:
        ok = False
        flags.append("synth_parse_failed")
        messages.append("Synthesizer output could not be parsed as JSON.")

    # ------------------------------------------------------------------
    # Derive confidence purely from verification outcomes
    # ------------------------------------------------------------------
    if not ok:
        confidence = "low"
    else:
        # If any non‑critical warning (e.g., truncation) present, downgrade
        if flags:
            confidence = "medium"
        else:
            confidence = "high"

    return {
        "ok": ok,
        "confidence": confidence,
        "flags": flags,
        "messages": messages,
    }
