from typing import List

from .catalog.models import MetricDefinition

def seed_metrics(tenant_id: str = "default") -> List[MetricDefinition]:
    """Create a set of realistic metric definitions for a tenant.

    The SQL templates are deliberately simple DuckDB queries that operate on the
    ``sales`` / ``data`` table loaded by :class:`DataSource`. They are **never** exposed to
    the planner LLM – only the ``name``, ``synonyms`` and ``description`` are
    shared.
    """
    metrics = [
        MetricDefinition(
            name="total_revenue",
            tenant_id=tenant_id,
            description="Total revenue across all rows.",
            synonyms=["revenue", "sales_total"],
            sql_template="SELECT SUM(revenue) AS total_revenue FROM sales",
            allowed_filters=[],
            version=1,
            status="approved",
        ),
        MetricDefinition(
            name="order_count",
            tenant_id=tenant_id,
            description="Number of orders.",
            synonyms=["orders", "count_orders"],
            sql_template="SELECT COUNT(*) AS order_count FROM sales",
            allowed_filters=[],
            version=1,
            status="approved",
        ),
        MetricDefinition(
            name="avg_order_value",
            tenant_id=tenant_id,
            description="Average revenue per order.",
            synonyms=["average_order_value", "aov"],
            sql_template="SELECT AVG(revenue) AS avg_order_value FROM sales",
            allowed_filters=[],
            version=1,
            status="approved",
        ),
        MetricDefinition(
            name="revenue_by_region",
            tenant_id=tenant_id,
            description="Revenue broken down by region.",
            synonyms=["region_revenue"],
            sql_template="SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region",
            allowed_filters=["region"],
            version=1,
            status="approved",
        ),
        MetricDefinition(
            name="customer_lifetime_value",
            tenant_id=tenant_id,
            description="Sum of revenue per customer.",
            synonyms=["clv"],
            sql_template="SELECT customer_id, SUM(revenue) AS clv FROM sales GROUP BY customer_id",
            allowed_filters=["customer_id"],
            version=1,
            status="approved",
        ),
    ]
    return metrics
