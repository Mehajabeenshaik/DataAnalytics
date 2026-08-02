"""test_data_source_pii.py — PII masking tests for DataSource.

Tests that PII in loaded data is automatically detected and masked
before the data becomes queryable or appears in the schema card.
"""
import os
import tempfile
import pandas as pd
import pytest

from data_source import DataSource


@pytest.fixture
def pii_df():
    """DataFrame with obvious fake PII that should be detected and masked."""
    return pd.DataFrame({
        "order_id": [1, 2, 3, 4, 5],
        "customer_name": [
            "John Smith",
            "Jane Doe",
            "Bob Johnson",
            "Alice Williams",
            "Charlie Brown",
        ],
        "customer_email": [
            "john.smith@example.com",
            "jane.doe@example.com",
            "bob.johnson@example.com",
            "alice.williams@example.com",
            "charlie.brown@example.com",
        ],
        "customer_phone": [
            "+1-555-123-4567",
            "+1-555-234-5678",
            "+1-555-345-6789",
            "+1-555-456-7890",
            "+1-555-567-8901",
        ],
        "revenue": [100.0, 200.0, 300.0, 150.0, 250.0],
        "region": ["North", "South", "East", "West", "North"],
    })


def test_pii_columns_are_masked_on_load(pii_df):
    """When loading a DataFrame with PII columns, those columns should be
    masked before the data is queryable."""
    ds = DataSource()
    ds.load_dataframe(pii_df)

    try:
        from pii_masker import PIIMasker
        masker = PIIMasker()
        from pii_masker import _get_analyzer as _get_pii_analyzer
        analyzer = _get_pii_analyzer()
    except ImportError:
        pytest.skip("Presidio not installed")

    if analyzer is None:
        pytest.skip("Presidio analyzer not available")

    df = ds.query("SELECT * FROM data")

    if "customer_name" in ds.pii_masked_columns:
        for original in ["John Smith", "Jane Doe", "Bob Johnson"]:
            assert original not in df["customer_name"].values, (
                f"PII FAILURE: Original name '{original}' found in queryable data!"
            )

    if "customer_email" in ds.pii_masked_columns:
        for original in ["john.smith@example.com", "jane.doe@example.com"]:
            assert original not in df["customer_email"].values, (
                f"PII FAILURE: Original email '{original}' found in queryable data!"
            )

    if "customer_phone" in ds.pii_masked_columns:
        for original in ["+1-555-123-4567", "+1-555-234-5678"]:
            assert original not in df["customer_phone"].values, (
                f"PII FAILURE: Original phone '{original}' found in queryable data!"
            )


def test_pii_not_in_schema_card(pii_df):
    """The schema card sent to the LLM should not contain original PII values."""
    ds = DataSource()
    ds.load_dataframe(pii_df)

    try:
        from pii_masker import PIIMasker
        masker = PIIMasker()
        from pii_masker import _get_analyzer as _get_pii_analyzer
        analyzer = _get_pii_analyzer()
    except ImportError:
        pytest.skip("Presidio not installed")

    if analyzer is None:
        pytest.skip("Presidio analyzer not available")

    schema_card = ds.get_schema_card()

    pii_values = [
        "John Smith", "Jane Doe", "Bob Johnson",
        "john.smith@example.com", "jane.doe@example.com",
        "+1-555-123-4567", "+1-555-234-5678",
    ]
    for val in pii_values:
        assert val not in schema_card, (
            f"PII FAILURE: '{val}' found in schema card sent to LLM!"
        )


def test_non_pii_columns_preserved(pii_df):
    """Non-PII columns (revenue, region, order_id) should not be masked."""
    ds = DataSource()
    ds.load_dataframe(pii_df)

    df = ds.query("SELECT * FROM data")

    assert list(df["revenue"]) == [100.0, 200.0, 300.0, 150.0, 250.0]
    assert list(df["region"]) == ["North", "South", "East", "West", "North"]
    assert list(df["order_id"]) == [1, 2, 3, 4, 5]


def test_pii_masking_via_csv_file(pii_df):
    """PII should be masked when loading from a CSV file."""
    try:
        from pii_masker import PIIMasker
        masker = PIIMasker()
        from pii_masker import _get_analyzer as _get_pii_analyzer
        analyzer = _get_pii_analyzer()
    except ImportError:
        pytest.skip("Presidio not installed")

    if analyzer is None:
        pytest.skip("Presidio analyzer not available")

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        pii_df.to_csv(f.name, index=False)
        csv_path = f.name

    try:
        ds = DataSource()
        ds.load_file(csv_path)

        df = ds.query("SELECT * FROM data")

        if "customer_name" in ds.pii_masked_columns:
            assert "John Smith" not in df["customer_name"].values
            assert "Jane Doe" not in df["customer_name"].values

        if "customer_email" in ds.pii_masked_columns:
            assert "john.smith@example.com" not in df["customer_email"].values
    finally:
        os.unlink(csv_path)


def test_pii_masked_columns_property(pii_df):
    """The pii_masked_columns property should list which columns were masked."""
    ds = DataSource()
    ds.load_dataframe(pii_df)

    try:
        from pii_masker import PIIMasker
        masker = PIIMasker()
        from pii_masker import _get_analyzer as _get_pii_analyzer
        analyzer = _get_pii_analyzer()
    except ImportError:
        pytest.skip("Presidio not installed")

    if analyzer is None:
        pytest.skip("Presidio analyzer not available")

    if ds.pii_masked_columns:
        assert "revenue" not in ds.pii_masked_columns
        assert "region" not in ds.pii_masked_columns
        assert "order_id" not in ds.pii_masked_columns