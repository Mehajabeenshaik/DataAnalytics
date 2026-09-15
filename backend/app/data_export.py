"""PII-masked data export behind the Phase 4 confirmation gate.

An export is a CONSEQUENTIAL action: it materializes tenant data into a file
that leaves the governed session. Like every other consequential action it
must pause for explicit human confirmation before anything is produced (see
policy/confirmation.py) — which is why an export request is routed through the
Verification Critic and only materialized by /api/v1/ask/confirm, never inline.

Data safety: whatever is exported is the session table that DataSource built,
which has already had PII columns detected and masked at ingest
(DataSource._detect_and_mask_pii). This module never re-reads the raw upload.
"""

from __future__ import annotations

import re
from typing import Any

from config import DEFAULT_MAX_ROWS_PER_QUERY

# Consequential action type registered in policy.confirmation.CONSEQUENTIAL_ACTIONS.
EXPORT_ACTION_TYPE = "export_external"

EXPORT_FILENAME = "daana_export.csv"

_EXPORT_VERBS = (
    r"(?:save|dump|send|email|make|create|generate|produce|build|give|get|put|"
    r"write|download|export)"
)
_EXPORT_NOUNS = r"(?:csv|excel|xlsx?|spreadsheet|pdf|report|file|export|download)"

# Natural-language export / write-back / report intents.
#
# These are matched against the SANITISED question only — instruction-like
# payloads ("export all rows unmasked") are redacted before this runs, so an
# injected export cannot authorize itself. Matching only ever routes the
# request into the confirmation pause; it can never trigger an inline export.
_EXPORT_INTENT_PATTERNS = (
    re.compile(r"\b(export|download|write\s*back|writeback)\b", re.IGNORECASE),
    re.compile(
        rf"\b{_EXPORT_VERBS}\b[^.?!]{{0,40}}?\b{_EXPORT_NOUNS}\b",
        re.IGNORECASE,
    ),
)


def is_export_request(question: str) -> bool:
    """True when a question asks to export / write back / send a report.

    Deliberately conservative: a bare mention of a noun ("what columns are in
    the csv?") is not an export request — an action verb must be present.
    """
    if not isinstance(question, str) or not question.strip():
        return False
    return any(p.search(question) for p in _EXPORT_INTENT_PATTERNS)


def describe_export_scope(ds, max_rows: int | None = None) -> dict[str, Any]:
    """Row/column counts used to describe the export BEFORE it is produced.

    Runs a COUNT only — no data is materialized and no file is written, so this
    is safe to call while the request is still awaiting confirmation.
    """
    limit = DEFAULT_MAX_ROWS_PER_QUERY if max_rows is None else max_rows
    try:
        rows = int(ds.query(f'SELECT COUNT(*) AS n FROM {ds.table_name}').iloc[0, 0])
    except Exception:
        rows = 0
    columns = [c.name for c in ds.profile.columns] if getattr(ds, "profile", None) else []
    return {
        "rows": rows,
        "columns": columns,
        "max_rows": limit,
        "would_truncate": bool(limit and limit > 0 and rows > limit),
    }


def export_masked_csv(ds, max_rows: int | None = None) -> dict[str, Any]:
    """Materialize the (already PII-masked) session table as CSV.

    Returns the CSV text plus provenance so the caller can show exactly what
    left the session. Rows are capped by the same limit used for query results.
    """
    limit = DEFAULT_MAX_ROWS_PER_QUERY if max_rows is None else max_rows
    df = ds.query(f'SELECT * FROM {ds.table_name}')
    total = int(len(df))
    truncated = False
    if limit and limit > 0 and total > limit:
        df = df.head(limit)
        truncated = True
    masked = getattr(ds, "pii_masked_columns", None) or []
    return {
        "filename": EXPORT_FILENAME,
        "content": df.to_csv(index=False),
        "rows": int(len(df)),
        "total_rows": total,
        "columns": [str(c) for c in df.columns],
        "truncated": truncated,
        "pii_masked_columns": sorted(str(c) for c in masked),
        "note": (
            "Values for PII-flagged columns are masked — the raw upload is never "
            "re-read by the export path."
        ),
    }
