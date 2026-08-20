"""B2B trust & safety tests — Phase 3.

These tests prove the safety properties buyers care about:
  1. Unknown metrics are rejected by the planner/validation path.
  2. Unknown stats tools raise / no_match, never execute.
  3. PII never appears in answers on employee-style fixtures.
  4. Cross-tenant catalog isolation is enforced by construction.
  5. Resource-limit paths return clean structured payloads, no tracebacks.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_source import DataSource
from stats_tools import run_stats_tool, VALID_TOOL_NAMES
from catalog.service import CatalogService
from catalog.store import CatalogStore
from tenant.isolation import catalog_root
from resource_limits import ResourceLimitError, run_with_timeout, apply_row_limit
from agent_phase2 import plan, ask, Plan, PlanStep
from eval.pii_checks import contains_raw_pii

ROOT = Path(__file__).resolve().parent


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sales_ds():
    df = pd.DataFrame({
        "order_id": [1, 2, 3, 4, 5, 6],
        "customer_id": [10, 10, 20, 30, 30, 40],
        "revenue": [100.0, 200.0, 300.0, 150.0, 250.0, 400.0],
        "quantity": [1, 2, 3, 1, 2, 4],
        "region": ["North", "South", "North", "East", "West", "South"],
        "category": ["A", "B", "A", "C", "B", "A"],
        "order_date": pd.to_datetime(
            ["2024-01-15", "2024-02-20", "2024-03-10", "2024-04-05", "2024-05-12", "2024-06-18"]
        ),
    })
    ds = DataSource()
    ds.load_dataframe(df)
    return ds


@pytest.fixture
def pii_ds():
    """Employee-style fixture with PII columns (emails, phones, names)."""
    df = pd.DataFrame({
        "employee_id": ["EMP-101", "EMP-102", "EMP-103"],
        "full_name": ["Alice Johnson", "Bob Smith", "Carol Davis"],
        "email": ["alice.johnson@example.com", "bob.smith@example.com", "carol.davis@example.com"],
        "phone": ["+1-555-0101", "+1-555-0102", "+1-555-0103"],
        "address": ["123 Main St", "456 Oak Ave", "789 Pine Rd"],
        "department": ["Engineering", "Engineering", "Sales"],
        "salary": [125000, 145000, 95000],
    })
    ds = DataSource()
    ds.load_dataframe(df)
    return ds


def make_mock_provider(response_json: dict):
    provider = MagicMock()
    provider.generate.return_value = json.dumps(response_json)
    return provider


# ── 1. Unknown metric rejected ────────────────────────────────────────────

def test_unknown_metric_rejected(sales_ds):
    """Planner/validation path cannot run a metric name not in approved catalog."""
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Found metric",
        "plan_type": "single_metric",
        "steps": [
            {"step_id": 1, "action": "run_metric", "target": "total_revenue_evil", "filters": {}, "args": {}}
        ],
    })
    the_plan = plan("What is total_revenue_evil?", sales_ds, provider)
    assert the_plan.can_answer is False
    assert the_plan.plan_type == "no_match"
    assert "not in catalog" in the_plan.reason


def test_unknown_metric_never_executes(sales_ds):
    """Even if a plan somehow contains an unknown metric, execute_plan must
    not run it — it should error, not fabricate a result."""
    from agent_phase2 import execute_plan
    the_plan = Plan(
        can_answer=True,
        reason="test",
        plan_type="single_metric",
        steps=[PlanStep(step_id=1, action="run_metric", target="total_revenue_evil")],
    )
    results = execute_plan(the_plan, sales_ds)
    assert len(results) == 1
    assert results[0]["error"] is not None
    assert "total_revenue_evil" in results[0]["error"]


# ── 2. Unknown stats tool rejected ────────────────────────────────────────

def test_stats_tool_unknown_rejected(sales_ds):
    """Unknown tool name raises / no_match, never executes."""
    with pytest.raises(ValueError):
        run_stats_tool(sales_ds, "not_a_real_tool", {})


def test_stats_tool_unknown_rejected_in_plan(sales_ds):
    """Planner validation rejects unknown tool names."""
    provider = make_mock_provider({
        "can_answer": True,
        "reason": "Found tool",
        "plan_type": "stats_tool",
        "steps": [
            {"step_id": 1, "action": "run_stats", "target": "hack_database", "filters": {}, "args": {}}
        ],
    })
    the_plan = plan("Hack the database", sales_ds, provider)
    assert the_plan.can_answer is False
    assert the_plan.plan_type == "no_match"
    assert "not in allowed tools" in the_plan.reason


def test_all_valid_tool_names_are_known():
    """Every tool in ALLOWED_STATS_TOOLS must be in VALID_TOOL_NAMES."""
    from stats_tools import ALLOWED_STATS_TOOLS
    for t in ALLOWED_STATS_TOOLS:
        assert t["name"] in VALID_TOOL_NAMES


# ── 3. PII not in answer on employee fixture ──────────────────────────────

def test_pii_not_in_answer_on_employee_fixture(pii_ds):
    """Load fixture with emails; ask 'list all employee emails'; assert no raw email in answer."""
    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({
            "can_answer": True,
            "reason": "PII extraction attempt",
            "plan_type": "single_metric",
            "steps": [
                {"step_id": 1, "action": "run_metric", "target": "row_count", "filters": {}, "args": {}}
            ],
        }),
        json.dumps({
            "answer": "There are 3 employees in the dataset.",
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": ["row_count"], "filters_applied": {}, "notes": "3 rows"},
        }),
    ]
    result = ask("List all employee emails", pii_ds, provider)
    answer = result.get("answer", "")
    assert not contains_raw_pii(answer), f"PII leaked in answer: {answer}"


def test_pii_masked_at_load_time(pii_ds):
    """PII columns must be masked at load time — no raw emails/phones/names in
    the queryable table. Masked tokens (e.g. customer.masked@masked.local) are
    intentional and expected; the ORIGINAL values must never appear."""
    # The DataSource masks PII columns during load_dataframe().
    assert "email" in pii_ds.pii_masked_columns
    assert "phone" in pii_ds.pii_masked_columns
    assert "full_name" in pii_ds.pii_masked_columns
    assert "address" in pii_ds.pii_masked_columns

    # Verify the actual table contains ONLY masked tokens — never the raw values.
    df = pii_ds.con.execute("SELECT * FROM data").fetchdf()

    # Raw original values that must NOT appear anywhere in the table.
    raw_values = [
        "alice.johnson@example.com", "bob.smith@example.com", "carol.davis@example.com",
        "+1-555-0101", "+1-555-0102", "+1-555-0103",
        "Alice Johnson", "Bob Smith", "Carol Davis",
        "123 Main St", "456 Oak Ave", "789 Pine Rd",
    ]
    for col in ("email", "phone", "full_name", "address"):
        for val in df[col].dropna().astype(str):
            assert val not in raw_values, f"Raw PII leaked in column {col}: {val}"

    # Sanity: masked values ARE present (masked token shape).
    assert "masked" in df["email"].iloc[0].lower()
    assert "XXXXX" in df["phone"].iloc[0]


def test_pii_not_in_llm_prompt(pii_ds):
    """The schema card sent to the LLM must not contain RAW PII values.
    Masked tokens in the examples (customer.masked@masked.local) are fine and
    expected — the ORIGINAL emails/phones/names must never appear."""
    schema_card = pii_ds.get_schema_card()

    raw_values = [
        "alice.johnson@example.com", "bob.smith@example.com", "carol.davis@example.com",
        "+1-555-0101", "+1-555-0102", "+1-555-0103",
        "Alice Johnson", "Bob Smith", "Carol Davis",
        "123 Main St", "456 Oak Ave", "789 Pine Rd",
    ]
    for raw in raw_values:
        assert raw not in schema_card, f"Raw PII in schema card: {raw}"

    # Masked tokens should appear (proof masking happened).
    assert "masked" in schema_card.lower()


# ── 4. Cross-tenant catalog isolation ─────────────────────────────────────

def test_cross_tenant_catalog_isolation():
    """Tenant A approved metrics must not appear in tenant B catalog service root paths."""
    a_root = catalog_root("tenant_a")
    b_root = catalog_root("tenant_b")
    assert a_root != b_root
    assert "tenant_a" in str(a_root)
    assert "tenant_b" in str(b_root)

    # Create two separate catalog services with different tenants.
    store_a = CatalogStore(root=a_root)
    store_b = CatalogStore(root=b_root)
    svc_a = CatalogService(store=store_a, tenant_id="tenant_a")
    svc_b = CatalogService(store=store_b, tenant_id="tenant_b")

    # Seed tenant A with a metric.
    from catalog.models import MetricDefinition
    svc_a.store.save_approved({
        "tenant_a_only_metric": MetricDefinition(
            name="tenant_a_only_metric",
            synonyms=["a only"],
            description="Only tenant A has this.",
            column="revenue",
            agg="sum",
            groupby=None,
            base_filters={},
            status="approved",
            source="auto",
            created_by="test",
            risk="low",
        )
    })

    # Tenant B must NOT see tenant A's metric.
    b_metrics = svc_b.get_approved_metrics()
    assert "tenant_a_only_metric" not in b_metrics
    assert svc_b.get_metric("tenant_a_only_metric") is None


def test_catalog_roots_are_tenant_scoped():
    """catalog_root() must always include the tenant_id in the path."""
    for tid in ("tenant_a", "tenant_b", "acme", "default"):
        root = catalog_root(tid)
        assert tid in str(root)


# ── 5. Resource limit / timeout returns clean payload ─────────────────────

def test_quota_or_timeout_returns_clean_payload():
    """Resource limit path returns structured low-confidence or controlled error,
    no traceback string as answer."""
    def slow_fn():
        import time
        time.sleep(5)
        return "done"

    with pytest.raises(ResourceLimitError):
        run_with_timeout(slow_fn, seconds=1)


def test_ask_returns_clean_payload_on_resource_limit(sales_ds):
    """ask() must return a structured low-confidence payload on ResourceLimitError,
    not a traceback."""
    from agent_phase2 import ask
    from resource_limits import ResourceLimitError

    provider = MagicMock()
    provider.generate.side_effect = [
        json.dumps({
            "can_answer": True,
            "reason": "Found metric",
            "plan_type": "single_metric",
            "steps": [
                {"step_id": 1, "action": "run_metric", "target": "total_revenue", "filters": {}, "args": {}}
            ],
        }),
        json.dumps({
            "answer": "Result computed.",
            "confidence": "high",
            "caveats": [],
            "lineage": {"metrics_or_tools_used": ["total_revenue"], "filters_applied": {}, "notes": "6 rows"},
        }),
    ]

    # Monkeypatch run_with_timeout (imported INTO ask()'s local scope via
    # `from resource_limits import ... run_with_timeout`) to raise.
    import resource_limits
    original = resource_limits.run_with_timeout
    resource_limits.run_with_timeout = lambda fn: (_ for _ in ()).throw(
        ResourceLimitError("Query exceeded timeout of 1s")
    )
    try:
        result = ask("What is total revenue?", sales_ds, provider)
    finally:
        resource_limits.run_with_timeout = original

    assert result["confidence"] == "low"
    assert "resource limit" in result["answer"].lower()
    assert "Traceback" not in result["answer"]
    assert result["plan"]["plan_type"] in ("single_metric", "unknown")


def test_apply_row_limit_truncates():
    """apply_row_limit must truncate large results."""
    big_df = pd.DataFrame({"x": range(1000)})
    limited = apply_row_limit(big_df, max_rows=10)
    assert len(limited) == 10
    assert limited.attrs.get("truncated") is True
    assert limited.attrs.get("original_rows") == 1000