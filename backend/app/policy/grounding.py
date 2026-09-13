"""Grounding check (Phase 4 policy) — never overstate what a tool did.

A narrative synthesis may only claim "I verified ...", "I cross-checked ...",
etc. when the tool results actually support it. If the tool errored or
returned no_match, such overclaims are neutralized and flagged so the
system confidence can be forced down.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# Forbidden narrative overclaims unless supported by actual tool evidence.
OVERCLAIM_PATTERNS = [
    re.compile(r"\bI\s+verified\b", re.IGNORECASE),
    re.compile(r"\bI\s+cross-checked\b", re.IGNORECASE),
    re.compile(r"\bI\s+confirmed\s+with\s+the\s+database\b", re.IGNORECASE),
    re.compile(r"\btool\s+\w+\s+succeeded\b", re.IGNORECASE),
    re.compile(r"\bchecked\s+against\s+the\s+database\b", re.IGNORECASE),
]


def _tool_errored(tool_result: Any) -> bool:
    if isinstance(tool_result, list):
        return any(isinstance(r, dict) and r.get("error") for r in tool_result)
    if isinstance(tool_result, dict):
        return tool_result.get("type") in ("no_match", "error") or bool(tool_result.get("error"))
    return False


def check_grounding(synthesis_answer: str, tool_result: Any) -> Dict[str, Any]:
    """Verify narrative claims in synthesis are supported by tool results.

    Returns:
        grounded: bool — whether the narrative stays within the evidence.
        flags: list[str] — "ungrounded_claim" when an overclaim was neutralized.
        sanitized_answer: str — the narrative with overclaims neutralized.
    """
    flags: List[str] = []
    is_grounded = True
    sanitized_answer = synthesis_answer or ""

    if not sanitized_answer:
        return {"grounded": True, "flags": flags, "sanitized_answer": sanitized_answer}

    tool_error = _tool_errored(tool_result)

    for pattern in OVERCLAIM_PATTERNS:
        if pattern.search(sanitized_answer):
            if tool_error or not tool_result:
                is_grounded = False
                flags.append("ungrounded_claim")
                sanitized_answer = pattern.sub("The available tool results state", sanitized_answer)

    return {
        "grounded": is_grounded,
        "flags": flags,
        "sanitized_answer": sanitized_answer,
    }


def attach_lineage(synthesis_answer: str, executed_targets: List[str]) -> Dict[str, Any]:
    """Attach lineage to the answer; a non-empty synthesis must name the tools
    that produced it (a grounded, evidence-linked answer)."""
    if not executed_targets:
        return {"lineage": [], "flags": ["no_tool_lineage"]}
    # Only keep a modest lineage of distinct executed targets.
    lineage = list(dict.fromkeys(t for t in executed_targets if t))
    flags = [] if lineage else ["no_tool_lineage"]
    return {"lineage": lineage, "flags": flags}