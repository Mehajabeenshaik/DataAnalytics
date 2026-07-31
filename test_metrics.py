"""Tests for the metrics catalog and the LLM-facing metric selector.

These tests verify that:
- Every metric in METRICS has all required fields.
- The LLM catalog (get_metric_catalog_for_llm) never exposes SQL logic.
- ALLOWED_FILTER_COLUMNS is a subset of the data-layer allowlist.
"""
from metrics import METRICS, ALLOWED_FILTER_COLUMNS, get_metric_catalog_for_llm


REQUIRED_METRIC_FIELDS = {"synonyms", "description", "column", "agg", "groupby", "base_filters"}
VALID_AGG_TYPES = {"sum", "nunique", "derived_aov", "derived_refund_rate"}


def test_metrics_have_all_required_fields():
    """Every metric must have all required keys defined."""
    for name, metric in METRICS.items():
        missing = REQUIRED_METRIC_FIELDS - set(metric.keys())
        assert not missing, f"Metric '{name}' is missing fields: {missing}"


def test_metric_synonyms_are_lists():
    """synonyms must be a list of strings (used for LLM prompt matching)."""
    for name, metric in METRICS.items():
        syns = metric["synonyms"]
        assert isinstance(syns, list), f"Metric '{name}' synonyms must be a list"
        assert all(isinstance(s, str) for s in syns), f"Metric '{name}' synonyms must be strings"


def test_metric_descriptions_are_strings():
    """description must be a non-empty string."""
    for name, metric in METRICS.items():
        desc = metric["description"]
        assert isinstance(desc, str) and desc, f"Metric '{name}' description must be a non-empty string"


def test_metrics_have_valid_aggregation_types():
    """agg must be one of the known aggregation types."""
    for name, metric in METRICS.items():
        assert metric["agg"] in VALID_AGG_TYPES, (
            f"Metric '{name}' has unknown agg '{metric['agg']}'. "
            f"Valid types: {VALID_AGG_TYPES}"
        )


def test_metrics_base_filters_are_dicts():
    """base_filters must be a dict (even if empty)."""
    for name, metric in METRICS.items():
        assert isinstance(metric["base_filters"], dict), (
            f"Metric '{name}' base_filters must be a dict"
        )


def test_groupby_metrics_have_valid_groupby_column():
    """If groupby is not None, it must be a string."""
    for name, metric in METRICS.items():
        gb = metric["groupby"]
        if gb is not None:
            assert isinstance(gb, str), f"Metric '{name}' groupby must be a string or None"


def test_get_metric_catalog_excludes_sql_logic():
    """The LLM catalog must never expose column, agg, groupby, or base_filters."""
    catalog = get_metric_catalog_for_llm()
    for entry in catalog:
        assert "name" in entry
        assert "synonyms" in entry
        assert "description" in entry
        # Critical: no SQL logic should leak to the LLM
        assert "column" not in entry, f"Metric '{entry['name']}' leaked 'column' to LLM catalog"
        assert "agg" not in entry, f"Metric '{entry['name']}' leaked 'agg' to LLM catalog"
        assert "groupby" not in entry, f"Metric '{entry['name']}' leaked 'groupby' to LLM catalog"
        assert "base_filters" not in entry, f"Metric '{entry['name']}' leaked 'base_filters' to LLM catalog"


def test_get_metric_catalog_returns_all_metrics():
    """The LLM catalog must include every metric in METRICS."""
    catalog = get_metric_catalog_for_llm()
    catalog_names = {entry["name"] for entry in catalog}
    assert catalog_names == set(METRICS.keys()), (
        f"Catalog names {catalog_names} != METRICS keys {set(METRICS.keys())}"
    )


def test_allowed_filter_columns_is_list():
    """ALLOWED_FILTER_COLUMNS must be a list of strings."""
    assert isinstance(ALLOWED_FILTER_COLUMNS, list)
    assert all(isinstance(c, str) for c in ALLOWED_FILTER_COLUMNS)


def test_allowed_filter_columns_subset_of_data_layer():
    """The AI-agent allowlist must be a subset of the data-layer allowlist."""
    from data_layer import _ALLOWED_FILTER_COLUMNS
    agent_set = set(ALLOWED_FILTER_COLUMNS)
    data_set = set(_ALLOWED_FILTER_COLUMNS)
    assert agent_set.issubset(data_set), (
        f"Agent allowlist has columns not in data-layer allowlist: "
        f"{agent_set - data_set}"
    )