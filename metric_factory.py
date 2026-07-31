"""
Auto-generate a high-quality, safe metric catalog from a DataSource profile.
The LLM only ever sees name / synonyms / description.
"""

from __future__ import annotations

from data_source import DataSource, TableProfile


def _suggest_synonyms(col: str, kind: str) -> list[str]:
    base = col.replace("_", " ")
    if kind == "sum":
        return [base, f"total {base}", f"sum of {base}", f"{base} total"]
    if kind == "count":
        return [f"number of {base}", f"count of {base}", f"how many {base}"]
    if kind == "avg":
        return [f"average {base}", f"avg {base}", f"mean {base}"]
    if kind == "by":
        return [f"{base} by", f"breakdown by {base}", f"{base} split"]
    return [base]


def generate_metrics(ds: DataSource) -> dict:
    """
    Returns a METRICS dict compatible with the existing agent contract:
    {
      name: {
        synonyms, description, column, agg, groupby, base_filters
      }
    }
    """
    if not ds.profile:
        raise RuntimeError("DataSource has no profile. Load data first.")

    metrics: dict = {}
    profile: TableProfile = ds.profile
    numeric_cols = [c for c in profile.columns if c.is_numeric]
    cat_cols = [c for c in profile.columns if c.is_categorical]
    id_like = [c for c in profile.columns if "id" in c.name.lower()]

    # 1. Global sums for every numeric column
    for col in numeric_cols:
        name = f"total_{col.name}"
        metrics[name] = {
            "synonyms": _suggest_synonyms(col.name, "sum"),
            "description": f"Sum of {col.name} across all rows.",
            "column": col.name,
            "agg": "sum",
            "groupby": None,
            "base_filters": {},
        }

        name_avg = f"avg_{col.name}"
        metrics[name_avg] = {
            "synonyms": _suggest_synonyms(col.name, "avg"),
            "description": f"Average (mean) of {col.name}.",
            "column": col.name,
            "agg": "mean",
            "groupby": None,
            "base_filters": {},
        }

    # 2. Row count
    metrics["row_count"] = {
        "synonyms": ["number of rows", "how many records", "count", "volume"],
        "description": "Total number of rows in the table.",
        "column": "*",
        "agg": "count",
        "groupby": None,
        "base_filters": {},
    }

    # 3. Distinct counts for ID-like or high-cardinality categoricals
    for col in id_like + [c for c in cat_cols if c.n_unique and c.n_unique > 10]:
        name = f"unique_{col.name}"
        metrics[name] = {
            "synonyms": _suggest_synonyms(col.name, "count") + [f"distinct {col.name}"],
            "description": f"Number of unique values in {col.name}.",
            "column": col.name,
            "agg": "nunique",
            "groupby": None,
            "base_filters": {},
        }

    # 4. Breakdowns: numeric × categorical (most valuable)
    for num in numeric_cols[:6]:  # keep catalog lean
        for cat in cat_cols[:5]:
            name = f"{num.name}_by_{cat.name}"
            metrics[name] = {
                "synonyms": [
                    f"{num.name} by {cat.name}",
                    f"{num.name} per {cat.name}",
                    f"breakdown of {num.name} by {cat.name}",
                ],
                "description": f"Sum of {num.name} grouped by {cat.name}.",
                "column": num.name,
                "agg": "sum",
                "groupby": cat.name,
                "base_filters": {},
            }

    return metrics


def get_metric_catalog_for_llm(metrics: dict) -> list[dict]:
    """Exactly the same contract as the original project."""
    return [
        {
            "name": name,
            "synonyms": m["synonyms"],
            "description": m["description"],
        }
        for name, m in metrics.items()
    ]