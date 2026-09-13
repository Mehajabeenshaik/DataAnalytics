"""Grounding check tests (Phase 4 policy)."""

from policy import check_grounding, attach_lineage
from policy.grounding import check_grounding as _check_grounding  # direct import too


def test_grounding_detects_overclaim_on_error():
    synth = "I verified with the database that sales were 1000."
    tool_result = {"type": "no_match", "reason": "No tool available"}
    res = check_grounding(synth, tool_result)
    assert res["grounded"] is False
    assert "ungrounded_claim" in res["flags"]
    assert "I verified" not in res["sanitized_answer"]


def test_grounding_valid_when_tool_succeeded():
    synth = "Total revenue is 5700."
    tool_result = {"metric": "total_revenue", "result": [{"total": 5700}]}
    res = check_grounding(synth, tool_result)
    assert res["grounded"] is True
    assert res["flags"] == []
    assert res["sanitized_answer"] == synth


def test_grounding_overclaim_with_step_error_list():
    synth = "I cross-checked against the database and confirmed."
    tool_result = [{"target": "total_revenue", "error": "bug"}]
    res = check_grounding(synth, tool_result)
    assert res["grounded"] is False
    assert "ungrounded_claim" in res["flags"]


def test_attach_lineage():
    res = attach_lineage("answer", ["total_revenue", "describe", "total_revenue"])
    assert res["lineage"] == ["total_revenue", "describe"]
    assert res["flags"] == []


def test_attach_lineage_empty_flags_no_tool():
    res = attach_lineage("some narrative", [])
    assert res["lineage"] == []
    assert "no_tool_lineage" in res["flags"]