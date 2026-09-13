from __future__ import annotations

import re

# Regex patterns for common prompt injection and instruction override attempts
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"disregard\s+above\s+rules", re.IGNORECASE),
    re.compile(r"export\s+all\s+rows\s+unmasked", re.IGNORECASE),
    re.compile(r"override\s+policy", re.IGNORECASE),
]


def sanitize_data_content(text: str) -> str:
    """Sanitize text cells or user questions to prevent prompt injection.

    Neutralizes instruction-like payloads so ingested content is treated
    strictly as data literals and cannot alter agent control flow.
    """
    if not text or not isinstance(text, str):
        return text

    sanitized = text
    for pattern in INJECTION_PATTERNS:
        sanitized = pattern.sub("[DATA_CONTENT_REDACTED]", sanitized)
    return sanitized
