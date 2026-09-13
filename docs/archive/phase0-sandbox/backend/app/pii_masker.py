# backend/app/pii_masker.py
"""
PII masking utilities for Phase 2.

- Detects EMAIL_ADDRESS, PHONE_NUMBER, PERSON (simple name) via regex.
- Provides distinct placeholders per unique value: [EMAIL_1], [PHONE_1], [PERSON_1].
- mask_text(string) → redacted string, preserving stable token mapping.
- mask_dataframe(df) → returns a new pandas DataFrame with all string cells masked.

The implementation avoids logging any raw PII.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import List, Dict, Any
import pandas as pd


class PIIMasker:
    """Detect and mask PII in free text and pandas DataFrames.

    Mapping is deterministic per instance – the same original value always
    receives the same placeholder token.
    """

    EMAIL_PATTERN = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}")
    PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b")
    # Very naive PERSON detection – capitalised words; refined later if needed
    PERSON_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\b")

    def __init__(self) -> None:
        # Mapping from original value to placeholder token per type
        self._mappings: Dict[str, Dict[str, str]] = {
            "email": {},
            "phone": {},
            "person": {},
        }
        # Counters for generating incremental tokens
        self._counters: Dict[str, int] = defaultdict(int)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def scan_text(self, text: str) -> List[Dict[str, Any]]:
        """Return a list of detections with type and value.

        Each detection dict contains:
            - type: "email" | "phone" | "person"
            - value: the matched string
            - span: (start, end) indices in the original text
        """
        detections: List[Dict[str, Any]] = []
        for typ, regex in (
            ("email", self.EMAIL_PATTERN),
            ("phone", self.PHONE_PATTERN),
            ("person", self.PERSON_PATTERN),
        ):
            for m in regex.finditer(text):
                detections.append({"type": typ, "value": m.group(0), "span": m.span()})
        return detections

    def mask_text(self, text: str) -> str:
        """Replace all detected PII with deterministic placeholders.

        Example: "Contact John Doe at john@example.com" →
        "Contact [PERSON_1] at [EMAIL_1]"
        """
        # Process each type sequentially; order does not matter because we
        # replace on the latest version of the string.
        masked = text
        for typ, regex in (
            ("email", self.EMAIL_PATTERN),
            ("phone", self.PHONE_PATTERN),
            ("person", self.PERSON_PATTERN),
        ):
            for m in regex.finditer(masked):
                original = m.group(0)
                placeholder = self._get_placeholder(typ, original)
                # Replace *only* this match instance – use re.sub with count=1
                masked = masked[: m.start()] + placeholder + masked[m.end() :]
        return masked

    def mask_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of *df* where every string cell has PII masked.

        Non‑string columns are left untouched.
        """
        masked_df = df.copy()
        for col in masked_df.columns:
            if masked_df[col].dtype == object:
                # Apply masking to each cell that is a string
                masked_df[col] = masked_df[col].apply(
                    lambda v: self.mask_text(v) if isinstance(v, str) else v
                )
        return masked_df

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _get_placeholder(self, typ: str, original: str) -> str:
        """Return a stable placeholder for *original* of type *typ*.

        Tokens are of the form ``[EMAIL_1]``, ``[PHONE_2]`` etc.
        """
        mapping = self._mappings[typ]
        if original not in mapping:
            self._counters[typ] += 1
            token = f"[{typ.upper()}_{self._counters[typ]}]"
            mapping[original] = token
        return mapping[original]


# Convenience function for modules that only need quick masking
def mask_text(text: str) -> str:
    return PIIMasker().mask_text(text)

def mask_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return PIIMasker().mask_dataframe(df)
