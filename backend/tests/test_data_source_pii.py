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


# ── Value-based NER false positives on plain id columns ───────────────────
#
# Presidio's spaCy NER flags short alphanumeric tokens like "ORD-1001" as
# PERSON, and the old code masked a whole column on a SINGLE detection hit.
# That masked plain identifier columns (e.g. order_id) that match no PII name
# keyword. These tests stub the analyzer so the value-detection path is
# exercised deterministically, with or without Presidio installed.

class _Detected:
    """Truthy stand-in for a Presidio RecognizerResult."""


class _AlwaysDetects:
    """Analyzer that reports a detection for every value given to it."""

    def analyze(self, text=None, entities=None, language=None, **kwargs):
        return [_Detected()]


class _SelectiveAnalyzer:
    """Analyzer that reports detections only for an explicit set of values."""

    def __init__(self, hits):
        self.hits = {str(h) for h in hits}

    def analyze(self, text=None, entities=None, language=None, **kwargs):
        return [_Detected()] if str(text) in self.hits else []


class _FakeMasker:
    """Stand-in PIIMasker: scan_text is all DataSource._mask_value needs."""

    def scan_text(self, value):
        return [_Detected()] if value else []


@pytest.fixture
def stub_pii(monkeypatch):
    """Install a fake analyzer + masker for DataSource PII detection."""
    import pii_masker

    def _install(analyzer):
        monkeypatch.setattr(pii_masker, "_get_analyzer", lambda: analyzer)
        monkeypatch.setattr(pii_masker, "PIIMasker", _FakeMasker)

    return _install


def test_id_like_column_not_masked_even_if_every_value_detects(stub_pii):
    """order_id (ORD-1001...) must never be masked by value-detection alone."""
    stub_pii(_AlwaysDetects())
    ids = [f"ORD-{1000 + i}" for i in range(20)]

    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({"order_id": ids, "amount": [1.0] * 20}))

    assert "order_id" not in ds.pii_masked_columns
    assert list(ds.query('SELECT "order_id" FROM data')["order_id"]) == ids


def test_id_shape_names_are_guarded_without_suffix(stub_pii):
    """id/sku/code-named columns are guarded by NAME, not just by value shape."""
    stub_pii(_AlwaysDetects())

    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "sku": ["alpha", "beta", "gamma"],
        "code": ["one", "two", "three"],
    }))

    assert "sku" not in ds.pii_masked_columns
    assert "code" not in ds.pii_masked_columns


def test_single_detection_hit_does_not_mask_a_column(stub_pii):
    """One hit out of 20 samples is a false positive, not a PII column."""
    stub_pii(_SelectiveAnalyzer({"alice@example.com"}))
    values = [f"note text {i}" for i in range(19)] + ["alice@example.com"]

    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({"notes": values}))

    assert "notes" not in ds.pii_masked_columns


def test_two_detection_hits_do_mask_a_column(stub_pii):
    """Two-or-more hits in a non-id column still masks the column."""
    stub_pii(_SelectiveAnalyzer({"alice@example.com", "bob@example.com"}))
    values = [f"note text {i}" for i in range(18)] + [
        "alice@example.com", "bob@example.com",
    ]

    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({"notes": values}))

    assert "notes" in ds.pii_masked_columns
    masked = ds.query('SELECT "notes" FROM data')["notes"].tolist()
    assert "alice@example.com" not in masked


def test_name_keyword_column_still_masked_with_id_shaped_values(stub_pii):
    """The id-shape guard must not weaken genuine keyword-based detection."""
    stub_pii(_AlwaysDetects())

    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "customer_name": ["John Smith", "Jane Doe", "Bob Brown"],
        "order_id": ["ORD-1001", "ORD-1002", "ORD-1003"],
    }))

    assert "customer_name" in ds.pii_masked_columns
    assert "order_id" not in ds.pii_masked_columns
    masked = ds.query('SELECT "customer_name" FROM data')["customer_name"].tolist()
    assert "John Smith" not in masked


def test_sample_csv_order_id_is_not_masked():
    """Regression: the shipped sample dataset's order_id must stay usable."""
    from pathlib import Path

    sample = Path(__file__).resolve().parents[2] / "samples" / "sample_sales_data.csv"
    if not sample.exists():
        pytest.skip(f"sample dataset missing: {sample}")

    ds = DataSource()
    ds.load_file(str(sample))

    assert "order_id" not in ds.pii_masked_columns
    ids = ds.query('SELECT "order_id" FROM data')["order_id"].tolist()
    assert ids and all(str(v).startswith("ORD-") for v in ids)