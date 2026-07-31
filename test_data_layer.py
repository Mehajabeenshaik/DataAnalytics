"""test_data_layer.py — Data layer tests including SQL-injection safety checks.

These tests cover:
  1. Basic smoke test: query_enriched() with no filters returns data.
  2. Filtered query using resolve_filter() works correctly.
  3. SECURITY: A malicious value passed as a filter VALUE is safely
     parameterized and does NOT execute as SQL.
  4. SECURITY: A filter referencing a column not in the allowlist raises
     ValueError immediately, before any SQL is executed.
"""
import pytest
import sqlite3
from data_layer import init_db, query_enriched, resolve_filter, DB_PATH

# ── Shared fixture ──────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def ensure_db():
    """Initialise (but do not force-reseed) the DB once for this module."""
    init_db()


# ── Existing behaviour: basic query ────────────────────────────────────

def test_query_enriched_no_filter():
    """query_enriched() with no arguments returns all enriched rows."""
    df = query_enriched()
    assert not df.empty, "orders_enriched view returned no rows"
    assert "order_status" in df.columns
    assert "line_total" in df.columns


def test_query_enriched_with_valid_filter():
    """query_enriched() with a valid filter dict returns a subset of rows."""
    df_all = query_enriched()
    df_completed = query_enriched(filters={"order_status": "completed"})
    # Filtered set must be non-empty and a proper subset of all rows.
    assert not df_completed.empty
    assert len(df_completed) < len(df_all)
    # Every row in the filtered result must have order_status == "completed".
    assert (df_completed["order_status"] == "completed").all()


def test_query_enriched_region_filter():
    """A customer_region filter returns only rows for that region."""
    df = query_enriched(filters={"customer_region": "South"})
    assert not df.empty
    assert (df["customer_region"] == "South").all()


def test_resolve_filter_builds_correct_clause():
    """resolve_filter() produces a correct parameterized clause and params list."""
    clause, params = resolve_filter({"order_status": "completed"})
    assert clause == "order_status = ?"
    assert params == ["completed"]


def test_resolve_filter_operator_tuple():
    """resolve_filter() handles (operator, value) tuple specs."""
    clause, params = resolve_filter({"order_year": (">", 2023)})
    assert "order_year > ?" in clause
    assert 2023 in params


def test_resolve_filter_in_list():
    """resolve_filter() handles a list-of-values spec as an IN clause."""
    clause, params = resolve_filter({"order_status": ["completed", "pending"]})
    assert "order_status IN (?,?)" in clause
    assert "completed" in params and "pending" in params


def test_resolve_filter_between():
    """resolve_filter() handles the BETWEEN dict spec."""
    clause, params = resolve_filter({"order_year": {"BETWEEN": (2023, 2025)}})
    assert "order_year BETWEEN ? AND ?" in clause
    assert params == [2023, 2025]


# ── SECURITY TEST 1: malicious VALUE is parameterized, not executed ─────

def test_malicious_value_is_parameterized_not_executed():
    """A SQL-injection string passed as a filter VALUE must be treated as a
    literal value — it must not drop the orders table or affect query results
    in any unexpected way.

    This test confirms parameterization holds by:
      a) Verifying the query runs without error (SQLite rejects a stray DDL
         statement embedded in a quoted value comparison — it simply finds no
         matching rows because no order_status equals that string).
      b) Verifying that the orders table still exists after the call (DROP
         TABLE did not execute).
    """
    malicious_value = "1=1; DROP TABLE orders;--"

    # The call must not raise any exception.
    df = query_enriched(filters={"order_status": malicious_value})

    # No row's order_status should equal that literal string.
    assert df.empty or not (df["order_status"] == malicious_value).any(), (
        "Unexpected: a row matched the injected string as a literal value"
    )

    # Verify the orders table was NOT dropped.
    conn = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert "orders" in tables, (
        "SECURITY FAILURE: 'orders' table no longer exists — SQL injection may have executed!"
    )


# ── SECURITY TEST 2: non-allowlisted column raises ValueError ───────────

def test_non_allowlisted_column_raises_value_error():
    """resolve_filter() must raise ValueError for any column outside the
    allowlist — this prevents LLM-generated column names from bypassing
    the filter guard.
    """
    with pytest.raises(ValueError, match="not in the filter allowlist"):
        resolve_filter({"customer_name": "anything"})

    with pytest.raises(ValueError, match="not in the filter allowlist"):
        resolve_filter({"sqlite_master": "anything"})

    with pytest.raises(ValueError, match="not in the filter allowlist"):
        resolve_filter({"1 OR 1=1--": "anything"})


# ── Existing script-mode output (preserved for backward compat) ─────────

def _run_legacy_print_tests():
    """Reproduce the original script-style output so existing CI output
    that parses stdout is unchanged."""
    init_db()
    df = query_enriched()

    print("First 5 rows:")
    print(df.head(5).to_string())
    print(f"\nShape: {df.shape}")
    print(f"\nColumns: {list(df.columns)}")

    completed = df[df["order_status"] == "completed"]
    revenue_by_region = completed.groupby("customer_region")["line_total"].sum().sort_values(ascending=False)
    print(f"\nRevenue by region:")
    print(revenue_by_region)

    revenue_by_category = completed.groupby("product_category")["line_total"].sum().sort_values(ascending=False)
    print(f"\nRevenue by category:")
    print(revenue_by_category)

    print(f"\nOrder status distribution:")
    print(df.drop_duplicates("order_id")["order_status"].value_counts())
