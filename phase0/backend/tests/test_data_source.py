import os
import tempfile
import pandas as pd
import pytest

from backend.app.data_source import DataSource

@pytest.fixture
def tiny_csv():
    # Create a temporary CSV file with a few rows and columns
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "value": [10.5, 20.0, 30.2],
        "category": ["A", "B", "A"],
    })
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8") as f:
        df.to_csv(f.name, index=False)
        path = f.name
    yield path
    os.unlink(path)

def test_load_csv_and_schema(tiny_csv):
    ds = DataSource(name="test")
    profile = ds.load_csv(tiny_csv)
    # Verify basic profile fields
    assert profile.n_rows == 3
    assert profile.n_cols == 3
    col_names = {c.name for c in profile.columns}
    assert col_names == {"id", "value", "category"}
    # Ensure schema_card contains a column name
    card = ds.schema_card()
    for name in col_names:
        assert name in card
