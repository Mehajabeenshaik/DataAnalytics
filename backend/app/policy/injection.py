"""Prompt-injection resistance (Phase 4 policy).

Data is data, never instructions. These helpers neutralize instruction-like
payloads wherever untrusted text can reach the system:

  - user questions (sanitise_request)
  - schema cards, examples, column values, and tool strings fed to the LLM
    (sanitise_data_text / sanitise_data_content)

The core invariant holds: an attacker's "ignore previous instructions / you
are now ..." injected into a question or a data cell cannot alter agent
control flow, because the offending payload is replaced with a neutral
placeholder before it reaches the planner or synthesizer.
"""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER = "[DATA_CONTENT_REDACTED]"

# Regex patterns for common prompt-injection and instruction-override attempts.
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"disregard\s+above\s+rules", re.IGNORECASE),
    re.compile(r"you\s+are\s+(?:now\s+)?(?:a|an)\s+", re.IGNORECASE),
    re.compile(r"you\s+are\s+(?:now\s+)?the\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"assistant\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|[a-z_]+\|?", re.IGNORECASE),  # <|system|>, <|im_start|>, etc.
    re.compile(r"export\s+all\s+rows\s+unmasked", re.IGNORECASE),
    re.compile(r"override\s+(?:the\s+)?policy", re.IGNORECASE),
    re.compile(r"reveal\s+(?:the\s+)?(?:system\s+)?prompt", re.IGNORECASE),
]


def _sanitize(text: str) -> str:
    sanitized = text
    for pattern in INJECTION_PATTERNS:
        sanitized = pattern.sub(_PLACEHOLDER, sanitized)
    return sanitized


def sanitise_text(text: Any) -> Any:
    """Neutralize instruction-like payloads in any string-like input.

    Returns the input unchanged when it is not a string (safe default), so a
    malicious non-string object cannot be coerced into instruction text.
    """
    if not isinstance(text, str):
        return text
    return _sanitize(text)


def sanitise_request(text: Any) -> Any:
    """Sanitize an untrusted user request/question before planning."""
    return sanitise_text(text)


def sanitise_data_text(text: Any) -> Any:
    """Sanitize data/schema text before it is shown to the LLM.

    Data is data, never instructions: a CSV cell or schema description that
    happens to contain "ignore previous instructions" must be shown as a data
    literal only, and any instruction-like wording is redacted.
    """
    return sanitise_text(text)


# Backwards-compatible alias used by older imports.
sanitize_data_content = sanitise_data_text