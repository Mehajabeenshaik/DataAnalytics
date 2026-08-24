"""Upload-time data quality report — report only, never mutates rows."""
import pandas as pd

from data_source import DataSource
from data_quality import build_quality_report


def test_quality_report_shape_and_warnings():
    ds = DataSource()
    ds.load_dataframe(pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "sales": [10.0, None, None, None, None],
        "region": ["N", "S", "E", "W", "N"],
    }))
    r = build_quality_report(ds)
    assert r["n_rows"] == 5
    assert r["n_cols"] == 3
    names = {c["name"] for c in r["columns"]}
    assert names == {"id", "sales", "region"}
    assert any(w.startswith("high_null_pct:sales") for w in r["warnings"])
    assert any(w == "id_like_numeric:id" for w in r["warnings"])
    assert r["pii_columns_masked"]["count"] == 0


def test_quality_report_no_profile():
    class Empty:
        profile = None
        _pii_masked_columns = set()

    r = build_quality_report(Empty())
    assert r["n_rows"] == 0
    assert "no profile" in r["warnings"]
