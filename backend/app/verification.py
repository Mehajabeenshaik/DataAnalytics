"""Post-hoc verification layer. Confidence is computed here, never trusted
from the LLM's self-reported field.

Phase 6 sanity checks (all computed, deterministic):
  1. count/row-count results must not exceed the source row count
  2. sum/mean of money/quantity-like fields must not go negative
  3. breakdown values must sum to within 1% of the overall total
  4. truncated result sets are flagged (high confidence requires
     "result not truncated")
  5. a synthesizer JSON parse-fallback forces low confidence regardless
     of what the LLM claimed

The execution layer is responsible for attaching verification metadata to
each step result entry:
  - ``_source_row_count``  (int | None)  rows the step actually saw
  - ``_breakdown``         (dict)        label->value for groupby-style results
  - ``_expected_total``    (float | None) overall aggregate for breakdown check
  - ``_truncated``         (bool)        set by row-limit truncation
and ``synthesize()`` attaches ``_parse_failed`` when the fallback JSON parser
was used. Without those keys the checks simply no-op (safe default).
"""
from __future__ import annotations

import re
from typing import Any


def _month_requested(question: str | None) -> bool:
    """True when the question names a calendar month (name, abbr, or YYYY-MM)."""
    if not question:
        return False
    from calendar import month_name, month_abbr

    ql = question.lower()
    for i in range(1, 13):
        if re.search(rf"\b{month_name[i].lower()}\b", ql) or re.search(
            rf"\b{month_abbr[i].lower()}\b", ql
        ):
            return True
    return bool(re.search(r"\b(20\d{2})-(\d{2})\b", ql))


def verify_breakdown_sums_to_total(
    breakdown: dict[str, Any] | None,
    total: float | None,
    rel_tol: float = 1e-4,
    abs_tol: float = 0.01,
) -> tuple[bool, str | None]:
    """Check that a breakdown dict's numeric values sum to the expected total.

    Returns (ok, message). Non-numeric breakdown values cause the check to
    be skipped (returns True, None) — we only verify when all values are
    numeric.
    """
    if not breakdown or total is None:
        return True, None
    try:
        s = 0.0
        for v in breakdown.values():
            if isinstance(v, (int, float)):
                s += float(v)
            else:
                return True, None  # non-numeric breakdown; skip
        if abs(s - float(total)) <= max(abs_tol, rel_tol * abs(float(total))):
            return True, None
        return False, f"Verification failed: breakdown does not sum to total (sum {s} != total {total})"
    except Exception:
        return True, None


def verify_answer(plan: Any, results: list[dict], synthesized: dict, question: str | None = None) -> dict:
    flags: list[str] = []

    parse_failed = synthesized.get("_parse_failed", False)
    exact_catalog_match = getattr(plan, "plan_type", None) == "single_metric"
    execution_error = any(r.get("error") for r in results)

    for r in results:
        val = r.get("result")
        target = (r.get("target") or "").lower()

        # Row-count sanity: a count result can't exceed source rows
        row_count = r.get("_source_row_count")
        if row_count is not None and isinstance(val, (int, float)):
            if "count" in target and val > row_count:
                flags.append(f"count_exceeds_row_count:{target}")

        # Non-negativity heuristic for money/quantity-like fields
        if isinstance(val, (int, float)) and val < 0:
            if any(kw in target for kw in ("revenue", "sales", "price", "amount", "quantity")):
                flags.append(f"unexpected_negative:{target}")

        # Breakdown-vs-total consistency (only if both present in this run)
        breakdown = r.get("_breakdown")
        total = r.get("_expected_total")
        if breakdown and total:
            ok, msg = verify_breakdown_sums_to_total(breakdown, total)
            if not ok:
                flags.append(f"breakdown_total_mismatch:{target}")

        # Truncated results can never be "high confidence"
        if r.get("_truncated"):
            flags.append(f"result_truncated:{target}")

    # Month guard (P0.5): if the question names a calendar month but no
    # executed step applied a month filter, the time filter was NOT applied —
    # the answer may be an unfiltered total. Force low confidence + caveat.
    if question and _month_requested(question):
        applied = any(
            isinstance(r.get("args"), dict) and r["args"].get("month") is not None
            for r in results
        )
        if not applied:
            flags.append("time_filter_not_applied")

    if execution_error or parse_failed:
        computed_confidence = "low"
    elif flags:
        computed_confidence = "low"
    elif exact_catalog_match:
        computed_confidence = "high"
    else:
        computed_confidence = "medium"

    return {
        "computed_confidence": computed_confidence,
        "flags": flags,
        "passed": not flags and not execution_error and not parse_failed,
    }