from backend.app.verification import verify_answer


def test_verify_answer_happy_path():
    plan = {"plan_type": "single_metric", "metric_name": "total_revenue"}
    results = {"total": 5700, "row_count": 4, "_source_profile": {"n_rows": 4}}
    synthesized = {"answer": "Total revenue is 5700", "confidence": "high", "lineage": ["total_revenue"], "caveats": []}

    res = verify_answer(plan, results, synthesized)
    assert res["ok"] is True
    assert res["confidence"] == "high"
    assert res["flags"] == []


def test_verify_answer_negative_revenue():
    plan = {"plan_type": "single_metric", "metric_name": "total_revenue"}
    results = {"total_revenue": -500, "row_count": 1}
    synthesized = {"answer": "Revenue is -500", "confidence": "high", "lineage": ["total_revenue"], "caveats": []}

    res = verify_answer(plan, results, synthesized)
    assert res["ok"] is False
    assert res["confidence"] == "low"
    assert "negative_value" in res["flags"]


def test_verify_answer_breakdown_mismatch():
    plan = {"plan_type": "single_metric", "metric_name": "revenue_by_region"}
    results = {
        "total": 5000,
        "breakdown": [{"region": "North", "value": 2000}, {"region": "South", "value": 2000}],
    }
    synthesized = {"answer": "Breakdown done", "confidence": "high", "lineage": ["revenue_by_region"], "caveats": []}

    res = verify_answer(plan, results, synthesized)
    assert res["ok"] is False
    assert "breakdown_mismatch" in res["flags"]
