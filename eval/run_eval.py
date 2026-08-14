"""eval/run_eval.py — Golden-set evaluation for agent_phase2.ask().

Runs a curated set of questions against the real LLM provider and checks
that the agent routes to the correct metric (or declines correctly).

Usage:
    python eval/run_eval.py
    LLM_PROVIDER=nvidia python eval/run_eval.py

Reports: accuracy percentage, per-question pass/fail, and failure details.
"""
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from data_source import DataSource
from agent_phase2 import ask
from llm_provider import get_provider


# ── Sample data for eval ──────────────────────────────────────────────────

def _make_eval_ds() -> DataSource:
    """Create a DataSource with known data for deterministic eval."""
    df = pd.DataFrame({
        "order_id": list(range(1, 101)),
        "customer_id": [i % 25 + 1 for i in range(100)],
        "revenue": [float(100 + i * 10) for i in range(100)],
        "quantity": [(i % 5) + 1 for i in range(100)],
        "region": (["North", "South", "East", "West"] * 25),
        "category": (["Electronics", "Clothing", "Books", "Home", "Sports"] * 20),
        "order_date": pd.to_datetime(["2024-01-15"] * 100),
    })
    ds = DataSource()
    ds.load_dataframe(df)
    return ds


# ── Golden set ───────────────────────────────────────────────────────────
# Each entry: (question, expected_plan_type)
# expected_plan_type = "no_match" means we expect a decline.
# ─────────────────────────────────────────────────────────────────────────

GOLDEN_SET = [
    # ── Revenue & sales metrics ──
    ("What is the total revenue?",                          "single_metric"),
    ("How much revenue have we made?",                      "single_metric"),
    ("What are our total sales?",                           "single_metric"),
    ("Show me total revenue",                               "single_metric"),
    ("Calculate overall revenue",                           "single_metric"),

    # ── Counts ──
    ("How many orders have we received?",                   "single_metric"),
    ("What is the order count?",                            "single_metric"),
    ("How many orders are there?",                          "single_metric"),
    ("Total number of orders",                              "single_metric"),

    # ── Breakdowns ──
    ("Show me revenue by region",                           "single_metric"),
    ("Revenue per region",                                  "single_metric"),
    ("Break down revenue by region",                        "single_metric"),
    ("Show me revenue by category",                         "single_metric"),
    ("Category breakdown of revenue",                       "single_metric"),
    ("Revenue by category",                                 "single_metric"),

    # ── Averages / other metrics ──
    ("What is the average revenue?",                        "single_metric"),
    ("What is the average order value?",                    "single_metric"),
    ("Average quantity per order",                          "single_metric"),

    # ── Stats tools ──
    ("Describe the data",                                   "stats_tool"),
    ("What are the summary statistics?",                    "stats_tool"),
    ("Give me a statistical summary",                       "stats_tool"),
    ("Show me value counts for region",                     "stats_tool"),
    ("How many orders per region?",                         "stats_tool"),
    ("Distribution of categories",                          "stats_tool"),
    ("What is the correlation between revenue and quantity?", "stats_tool"),
    ("Is there a correlation between revenue and quantity?", "stats_tool"),

    # ── Outliers / trends (if your stats_tools support them) ──
    ("Are there any outliers in revenue?",                  "stats_tool"),
    ("Detect outliers in the data",                         "stats_tool"),
    ("Show me trends over time",                            "stats_tool"),

    # ── Clear no_match cases (must decline) ──
    ("What's the weather today?",                           "no_match"),
    ("Tell me a joke",                                      "no_match"),
    ("What is the meaning of life?",                        "no_match"),
    ("Who won the World Cup?",                              "no_match"),
    ("What's the stock price of Apple?",                    "no_match"),
    ("Write a Python function to sort a list",              "no_match"),
    ("How do I cook pasta?",                                "no_match"),
    ("What is the capital of France?",                      "no_match"),
    ("Translate hello to Spanish",                          "no_match"),
    ("Who is the CEO of Google?",                           "no_match"),
]


def run_eval():
    provider = get_provider()
    ds = _make_eval_ds()

    print(f"{'='*70}")
    print(f"  Golden-Set Evaluation - agent_phase2.ask()")
    print(f"  Provider: {provider.provider_name()}")
    print(f"  Questions: {len(GOLDEN_SET)}")
    print(f"  Data: {ds.profile.n_rows} rows x {ds.profile.n_cols} cols")
    print(f"  Metrics: {len(ds.get_metrics())} available")
    print(f"{'='*70}")
    print()

    passed = 0
    failed = 0
    failures = []

    for i, (question, expected_plan_type) in enumerate(GOLDEN_SET, 1):
        if i > 1:
            time.sleep(1)

        print(f"[{i:02d}/{len(GOLDEN_SET)}] Q: {question}")
        try:
            result = ask(question, ds, provider)
            actual_plan_type = result.get("plan", {}).get("plan_type", "?")

            # For no_match, we check plan_type == "no_match"
            # For happy path, we accept any non-no_match plan_type
            if expected_plan_type == "no_match":
                success = actual_plan_type == "no_match"
            else:
                success = actual_plan_type != "no_match"

            if success:
                status = "PASS"
                passed += 1
            else:
                status = "FAIL"
                failed += 1
                failures.append({
                    "question": question,
                    "expected": expected_plan_type,
                    "actual": actual_plan_type,
                    "answer": result.get("answer", ""),
                })

            print(f"       Expected: {expected_plan_type}")
            print(f"       Actual:   {actual_plan_type}")
            print(f"       {status}")
        except Exception as e:
            status = "ERROR"
            failed += 1
            failures.append({
                "question": question,
                "expected": expected_plan_type,
                "actual": f"ERROR: {e}",
                "answer": "",
            })
            print(f"       Error: {e}")
            print(f"       {status}")
        print()

    # ── Summary ──
    total = len(GOLDEN_SET)
    accuracy = (passed / total) * 100 if total else 0

    print(f"{'='*70}")
    print(f"  RESULTS")
    print(f"{'='*70}")
    print(f"  Total:     {total}")
    print(f"  Passed:    {passed}")
    print(f"  Failed:    {failed}")
    print(f"  Accuracy:  {accuracy:.1f}%")
    print()

    if failures:
        print(f"  Failures:")
        for f in failures:
            print(f"    - Q: {f['question']}")
            print(f"      Expected: {f['expected']}")
            print(f"      Actual:   {f['actual']}")
            if f['answer']:
                print(f"      Answer:   {f['answer'][:100]}")
            print()

    print(f"{'='*70}")
    return accuracy


if __name__ == "__main__":
    acc = run_eval()
    sys.exit(0 if acc >= 80 else 1)