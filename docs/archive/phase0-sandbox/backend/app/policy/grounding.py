from __future__ import annotations

import re
from typing import Any, Dict, List

# Forbidden narrative overclaims unless supported by actual tool evidence
OVERCLAIM_PATTERNS = [
    re.compile(r"\bI\s+verified\b", re.IGNORECASE),
    re.compile(r"\bI\s+cross-checked\b", re.IGNORECASE),
    re.compile(r"\bI\s+confirmed\s+with\s+the\s+database\b", re.IGNORECASE),
    re.compile(r"\btool\s+\w+\s+succeeded\b", re.IGNORECASE),
]


def check_grounding(synthesis_answer: str, tool_result: Dict[str, Any]) -> Dict[str, Any]:
    """Verify that narrative claims in synthesis are supported by tool results.

    Pattern 3 (Never overstate what a tool did) & Pattern 4 (Tool availability honesty).
    """
    flags: List[str] = []
    is_grounded = True
    sanitized_answer = synthesis_answer

    # Check if tool_result contains error or no_match
    is_tool_error = tool_result.get("type") in ("no_match", "error") or "error" in tool_result

    for pattern in OVERCLAIM_PATTERNS:
        if pattern.search(synthesis_answer):
            if is_tool_error or not tool_result:
                is_grounded = False
                flags.append("ungrounded_claim")
                # Neutralize overclaim in narrative
                sanitized_answer = pattern.sub("The available tool results state", sanitized_answer)

    return {
        "grounded": is_grounded,
        "flags": flags,
        "sanitized_answer": sanitized_answer,
    }
