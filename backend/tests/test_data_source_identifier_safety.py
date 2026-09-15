"""SQL-identifier safety for untrusted uploaded headers (injection regression).

Uploaded CSV headers become DuckDB column identifiers, and stats_tools.py
interpolates those names directly into SQL *identifier* position inside double
quotes:  f'SELECT SUM("{value_col}") ...'.  _validate_column() only checks the
name EXISTS in the profile, so a header containing a double quote used to break
out of the quoting and run arbitrary DDL (DuckDB executes multi-statement
strings).  The injection surface is the uploaded file, NOT the LLM, so the
"LLM never writes SQL" invariant did not cover it.

The fix sanitizes every header ONCE at ingest, so no downstream f-string can
ever see an identifier outside [A-Za-z0-9_].
"""

import re

import pandas as pd
import pytest

from data_source import DataSource, _sanitize_column_name


# ── _sanitize_column_name unit behaviour ──────────────────────────────────

def test_sanitize_strips_quoting_and_semicolons():
    seen: set[str] = set()
    name = _sanitize_column_name('x" ; DROP TABLE data; --', seen)
    assert re.fullmatch(r"[A-Za-z0-9_]+", name)
    assert '"' not in name and ";" not in name and " " not in name
    assert "--" not in name


def test_sanitize_prefixes_leading_digit():
    seen: set[str] = set()
    assert _sanitize_column_name("2024_sales", seen) == "col_2024_sales"


def test_sanitize_keeps_normal_names_unchanged():
    seen: set[str] = set()
    assert _sanitize_column_name("order_id", seen) == "order_id"
    assert _sanitize_column_name("sales", seen) == "sales"


def test_sanitize_deduplicates_collisions():
    seen: set[str] = set()
    assert _sanitize_column_name("a b", seen) == "a_b"
    assert _sanitize_column_name("a-b", seen) == "a_b_2"
    assert _sanitize_column_name("a.b", seen) == "a_b_3"


def test_sanitize_blank_header_becomes_placeholder():
    seen: set[str] = set()
    assert _sanitize_column_name("   ", seen) == "col"
    assert _sanitize_column_name("---", seen) == "col_2"


# ── End-to-end: a malicious header cannot survive into SQL ────────────────

def test_malicious_csv_header_is_neutralised(tmp_path):
    """A header that breaks out of "..." quoting must not execute or persist."""
    payload = 'id,"x"" ; DROP TABLE data; --",amount\n1,"a",2\n3,"b",4\n'
    csv_path = tmp_path / "evil_headers.csv"
    csv_path.write_text(payload, encoding="utf-8")

    ds = DataSource()
    ds.load_file(str(csv_path))

    columns = [c.name for c in ds.profile.columns]
    assert len(columns) == 3, columns
    assert all(re.fullmatch(r"[A-Za-z0-9_]+", c) for c in columns), columns

    # The table must still exist and be queryable — i.e. the DROP never ran.
    df = ds.query("SELECT * FROM data")
    assert len(df) == 2

    # The original header is retained only as a display label, never as SQL.
    assert all(
        re.fullmatch(r"[A-Za-z0-9_]+", sql_name)
        for sql_name in ds._original_column_names
    )


def test_downstream_stats_tool_is_safe_with_malicious_header(tmp_path):
    """Tools that interpolate column names must work on the sanitized name."""
    payload = 'region,"total"" ; DROP TABLE data; --"\nNorth,"10"\nNorth,"30"\nSouth,"5"\n'
    csv_path = tmp_path / "evil2.csv"
    csv_path.write_text(payload, encoding="utf-8")

    ds = DataSource()
    ds.load_file(str(csv_path))

    # Find the sanitized name of the malicious column and aggregate over it.
    target = next(
        sql_name
        for sql_name in ds._original_column_names
        if ds._original_column_names[sql_name] != sql_name
    )
    out = ds.query(f'SELECT SUM(CAST("{target}" AS DOUBLE)) AS v FROM data')
    assert float(out.iloc[0, 0]) == pytest.approx(45.0)
    # The table survived (the injected DROP TABLE never executed).
    assert len(ds.query("SELECT * FROM data")) == 3


def test_load_dataframe_sanitizes_headers_and_keeps_dtypes():
    """Sanitization must not disturb ordinary numeric/string columns."""
    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "Order ID": [1, 2, 3],
        "Net Sales": [10.5, 20.25, 30.0],
        "Region ": ["North", "South", "North"],
    }))

    assert [c.name for c in ds.profile.columns] == [
        "Order_ID", "Net_Sales", "Region",
    ]
    assert ds.query('SELECT SUM("Net_Sales") AS v FROM data').iloc[0, 0] == pytest.approx(60.75)
    # Display labels preserved for the UI / catalog.
    assert ds._original_column_names.get("Net_Sales") == "Net Sales"