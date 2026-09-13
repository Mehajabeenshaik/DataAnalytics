from backend.app.policy.grounding import check_grounding


def test_grounding_detects_overclaim_on_error():
    synth_answer = "I verified with the database that sales were 1000."
    tool_result = {"type": "no_match", "reason": "No tool available"}

    res = check_grounding(synth_answer, tool_result)
    assert res["grounded"] is False
    assert "ungrounded_claim" in res["flags"]
    assert "I verified" not in res["sanitized_answer"]


def test_grounding_valid_when_tool_succeeded():
    synth_answer = "Total revenue is 5700."
    tool_result = {"metric": "total_revenue", "result": [{"total": 5700}]}

    res = check_grounding(synth_answer, tool_result)
    assert res["grounded"] is True
    assert res["flags"] == []
    assert res["sanitized_answer"] == synth_answer
