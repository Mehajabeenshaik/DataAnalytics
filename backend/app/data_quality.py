"""Upload-time data quality report. Report only — never impute or drop rows."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _dtype_kind(col) -> str:
    if getattr(col, "is_temporal", False):
        return "date"
    if getattr(col, "is_numeric", False):
        return "numeric"
    if getattr(col, "is_categorical", False):
        return "categorical"
    return "text"


def build_quality_report(ds) -> dict[str, Any]:
    profile = getattr(ds, "profile", None)
    if not profile:
        return {
            "n_rows": 0,
            "n_cols": 0,
            "columns": [],
            "warnings": ["no profile"],
            "pii_columns_masked": {"count": 0, "names": []},
        }

    columns: list[dict[str, Any]] = []
    warnings: list[str] = []
    names = [c.name for c in profile.columns]
    dupes = {n for n, k in Counter(names).items() if k > 1}
    if dupes:
        warnings.append("duplicate_column_names:" + ",".join(sorted(dupes)))

    for c in profile.columns:
        n_rows = profile.n_rows or 0
        null_pct = round(100.0 * c.n_null / n_rows, 2) if n_rows else 0.0
        kind = _dtype_kind(c)
        columns.append({
            "name": c.name,
            "dtype_kind": kind,
            "kind": kind,
            "n_null": c.n_null,
            "null_pct": null_pct,
            "n_unique": getattr(c, "n_unique", None),
        })
        if null_pct > 20:
            warnings.append(f"high_null_pct:{c.name}:{null_pct}%")
        low = c.name.lower()
        if c.is_numeric and (low == "id" or low.endswith("_id")):
            warnings.append(f"id_like_numeric:{c.name}")
        if re.search(r"\.\d+$", c.name) and c.name not in dupes:
            warnings.append(f"duplicate_column_names:{c.name}")

    pii_names = sorted(getattr(ds, "_pii_masked_columns", set()) or [])
    return {
        "n_rows": profile.n_rows,
        "n_cols": len(profile.columns),
        "columns": columns,
        "warnings": warnings,
        "pii_columns_masked": {"count": len(pii_names), "names": pii_names},
    }
