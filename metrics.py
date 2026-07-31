""" Defined business metrics for orders_enriched.
The LLM is only ever allowed to choose FROM this list — it never
invents a metric or writes raw SQL/aggregation logic itself.
"""

METRICS = {
    "total_revenue": {
        "synonyms": ["sales", "revenue", "income", "total sales"],
        "description": "Total revenue from completed orders (line_total summed).",
        "column": "line_total",
        "agg": "sum",
        "groupby": None,
        "base_filters": {"order_status": "completed"},
    },
    "order_count": {
        "synonyms": ["number of orders", "how many orders", "order volume"],
        "description": "Count of distinct completed orders.",
        "column": "order_id",
        "agg": "nunique",
        "groupby": None,
        "base_filters": {"order_status": "completed"},
    },
    "avg_order_value": {
        "synonyms": ["AOV", "average order size", "average basket"],
        "description": "Total revenue divided by number of distinct completed orders.",
        "column": "line_total",
        "agg": "derived_aov",
        "groupby": None,
        "base_filters": {"order_status": "completed"},
    },
    "total_profit": {
        "synonyms": ["profit", "margin", "earnings"],
        "description": "Total profit (line_profit summed) from completed orders.",
        "column": "line_profit",
        "agg": "sum",
        "groupby": None,
        "base_filters": {"order_status": "completed"},
    },
    "revenue_by_region": {
        "synonyms": ["sales by region", "revenue per region", "regional sales"],
        "description": "Revenue broken down by customer_region.",
        "column": "line_total",
        "agg": "sum",
        "groupby": "customer_region",
        "base_filters": {"order_status": "completed"},
    },
    "revenue_by_category": {
        "synonyms": ["sales by category", "revenue per category", "category breakdown"],
        "description": "Revenue broken down by product_category.",
        "column": "line_total",
        "agg": "sum",
        "groupby": "product_category",
        "base_filters": {"order_status": "completed"},
    },
    "refund_rate": {
        "synonyms": ["returns", "cancellations", "return rate"],
        "description": "Share of orders with status 'returned' or 'cancelled', as a percentage.",
        "column": "order_id",
        "agg": "derived_refund_rate",
        "groupby": None,
        "base_filters": {},  # intentionally no status filter — needs to see all statuses
    },
}

ALLOWED_FILTER_COLUMNS = [
    "order_status", "payment_method", "customer_region",
    "order_year", "order_month", "product_category",
]


def get_metric_catalog_for_llm() -> list[dict]:
    """Only name/synonyms/description go to the LLM — never raw SQL logic."""
    return [
        {"name": name, "synonyms": m["synonyms"], "description": m["description"]}
        for name, m in METRICS.items()
    ]