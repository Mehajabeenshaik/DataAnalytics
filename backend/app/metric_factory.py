"""
Auto-generate a high-quality, safe metric catalog from a DataSource profile.
The LLM only ever sees name / synonyms / description.
"""

from __future__ import annotations

from data_source import DataSource, TableProfile


def _build_synonyms(column: str, agg: str) -> list[str]:
    col_l = column.lower().replace("_", " ")
    synonyms = []

    if agg == "sum":
        synonyms += [
            f"total {col_l}", f"{col_l} total", f"sum of {col_l}",
            f"how much {col_l}", f"overall {col_l}",
        ]
        if any(kw in col_l for kw in ("revenue", "sales", "income", "amount")):
            synonyms += ["revenue", "total revenue", "total sales", "sales total"]

    elif agg == "mean":
        synonyms += [
            f"average {col_l}", f"avg {col_l}", f"mean {col_l}",
            f"typical {col_l}",
        ]

    elif agg in ("max", "min"):
        word = "highest" if agg == "max" else "lowest"
        synonyms += [f"{word} {col_l}", f"maximum {col_l}" if agg == "max" else f"minimum {col_l}"]

    elif agg == "count":
        synonyms += [f"number of {col_l}", f"{col_l} count", f"count of {col_l}"]

    return synonyms


def _suggest_synonyms(col: str, kind: str) -> list[str]:
    base = col.replace("_", " ")
    if kind == "sum":
        return [base, f"total {base}", f"sum of {base}", f"{base} total", "sales"]
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

    # 1. Global statistics for every numeric column (sum, mean, min, max)
    for col in numeric_cols:
        col_clean = col.name.replace(" ", "_")
        name_sum = f"total_{col_clean}"
        metrics[name_sum] = {
            "synonyms": _build_synonyms(col.name, "sum"),
            "description": f"Sum of {col.name} across all rows.",
            "column": col.name,
            "agg": "sum",
            "groupby": None,
            "base_filters": {},
        }

        name_avg = f"avg_{col_clean}"
        metrics[name_avg] = {
            "synonyms": _build_synonyms(col.name, "mean"),
            "description": f"Average (mean) of {col.name}.",
            "column": col.name,
            "agg": "mean",
            "groupby": None,
            "base_filters": {},
        }

        name_max = f"max_{col_clean}"
        metrics[name_max] = {
            "synonyms": _build_synonyms(col.name, "max"),
            "description": f"Maximum value of {col.name}.",
            "column": col.name,
            "agg": "max",
            "groupby": None,
            "base_filters": {},
        }

        name_min = f"min_{col_clean}"
        metrics[name_min] = {
            "synonyms": _build_synonyms(col.name, "min"),
            "description": f"Minimum value of {col.name}.",
            "column": col.name,
            "agg": "min",
            "groupby": None,
            "base_filters": {},
        }

    # 2. Row count
    metrics["row_count"] = {
        "synonyms": [
            "how many rows", "row count", "number of rows",
            "how many records", "dataset size", "total rows",
        ],
        "description": "Total number of rows in the table.",
        "column": "*",
        "agg": "count",
        "groupby": None,
        "base_filters": {},
    }

    # 3. Distinct counts for ID-like or high-cardinality categoricals
    for col in id_like + [c for c in cat_cols if c.n_unique and c.n_unique > 5]:
        col_clean = col.name.replace(" ", "_")
        name = f"unique_{col_clean}"
        metrics[name] = {
            "synonyms": _suggest_synonyms(col.name, "count") + [f"distinct {col.name}"],
            "description": f"Number of unique values in {col.name}.",
            "column": col.name,
            "agg": "nunique",
            "groupby": None,
            "base_filters": {},
        }

    # 4. Comprehensive Breakdowns: numeric × categorical
    for num in numeric_cols:
        num_clean = num.name.replace(" ", "_")
        for cat in cat_cols:
            cat_clean = cat.name.replace(" ", "_")

            # Sum by group
            name_sum = f"{num_clean}_by_{cat_clean}"
            metrics[name_sum] = {
                "synonyms": [
                    f"{num.name} by {cat.name}",
                    f"{num.name} per {cat.name}",
                    f"breakdown of {num.name} by {cat.name}",
                    f"total {num.name} by {cat.name}",
                ],
                "description": f"Sum of {num.name} grouped by {cat.name}.",
                "column": num.name,
                "agg": "sum",
                "groupby": cat.name,
                "base_filters": {},
            }

            # Average by group
            name_avg = f"avg_{num_clean}_by_{cat_clean}"
            metrics[name_avg] = {
                "synonyms": [
                    f"average {num.name} by {cat.name}",
                    f"avg {num.name} per {cat.name}",
                    f"mean {num.name} by {cat.name}",
                ],
                "description": f"Average of {num.name} grouped by {cat.name}.",
                "column": num.name,
                "agg": "mean",
                "groupby": cat.name,
                "base_filters": {},
            }

    # 5. Categorical counts by group
    for cat in cat_cols:
        cat_clean = cat.name.replace(" ", "_")
        name_cnt = f"count_by_{cat_clean}"
        metrics[name_cnt] = {
            "synonyms": [f"count by {cat.name}", f"number of items per {cat.name}", f"distribution of {cat.name}"],
            "description": f"Row count grouped by {cat.name}.",
            "column": "*",
            "agg": "count",
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


def merge_auto_metrics_into_catalog(
    ds: DataSource,
    catalog_service,
    created_by: str = "system",
) -> int:
    """Merge auto-generated metrics into the durable catalog on first load.

    This is the bridge between the legacy in-memory auto-generation and the
    new governed catalog. It is a no-op (returns 0) if the catalog already
    has content — human-approved / previously seeded metrics are NEVER
    overwritten.

    Args:
        ds: The loaded DataSource (must have a profile).
        catalog_service: A catalog.service.CatalogService instance.
        created_by: Identity stamped on the seeded metrics.

    Returns:
        The number of metrics seeded (0 if the catalog was already populated).
    """
    return catalog_service.seed_from_datasource(ds, created_by=created_by)
