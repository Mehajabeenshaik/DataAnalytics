"""eval/run_eval.py — Golden-set evaluation for ai_agent.ask().

Runs a curated set of questions against the real LLM provider and checks
that the agent routes to the correct metric (or declines correctly).

Usage:
    python eval/run_eval.py
    LLM_PROVIDER=gemini python eval/run_eval.py

Reports: accuracy percentage, per-question pass/fail, and failure details.
"""
import os
import sys
import time

# Bootstrap .env before any project import
from dotenv import load_dotenv
load_dotenv()

# Add project root to path so we can import ai_agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_agent import ask
from llm_provider import get_provider


# ── Golden set ───────────────────────────────────────────────────────────
# Each entry: (question, expected_metric_used)
# expected_metric_used = None means we expect a no_match decline.
# ─────────────────────────────────────────────────────────────────────────

GOLDEN_SET = [
    # ── Happy path: should route to a specific metric ──
    ("What is our total revenue?",                    "total_revenue"),
    ("How much revenue have we made?",                 "total_revenue"),
    ("What are our total sales?",                      "total_revenue"),
    ("How many orders have we received?",             "order_count"),
    ("What is the order count?",                       "order_count"),
    ("How many completed orders are there?",          "order_count"),
    ("What is the average order value?",              "avg_order_value"),
    ("What is our AOV?",                              "avg_order_value"),
    ("What is our total profit?",                     "total_profit"),
    ("How much profit have we made?",                 "total_profit"),
    ("Show me revenue by region",                     "revenue_by_region"),
    ("What are sales by region?",                     "revenue_by_region"),
    ("Revenue per region",                            "revenue_by_region"),
    ("Show me revenue by category",                   "revenue_by_category"),
    ("What are sales by category?",                   "revenue_by_category"),
    ("Category breakdown of revenue",                "revenue_by_category"),
    ("What is the refund rate?",                      "refund_rate"),
    ("What percentage of orders are returned?",       "refund_rate"),
    ("What is our return rate?",                      "refund_rate"),

    # ── No-match: should decline gracefully ──
    ("What's the weather today?",                     None),
    ("Tell me a joke",                                None),
    ("What is the meaning of life?",                  None),
    ("Who won the World Cup?",                        None),
    ("What's the stock price of Apple?",              None),
]


def run_eval():
    provider = get_provider()
    print(f"{'='*70}")
    print(f"  Golden-Set Evaluation — ai_agent.ask()")
    print(f"  Provider: {provider.provider_name()}")
    print(f"  Questions: {len(GOLDEN_SET)}")
    print(f"{'='*70}")
    print()

    passed = 0
    failed = 0
    failures = []

    for i, (question, expected_metric) in enumerate(GOLDEN_SET, 1):
        # Rate-limit: pause between calls to avoid 429s
        if i > 1:
            time.sleep(1)

        print(f"[{i:02d}/{len(GOLDEN_SET)}] Q: {question}")
        try:
            result = ask(question, provider)
            actual_metric = result.get("metric_used")

            if actual_metric == expected_metric:
                status = "✅ PASS"
                passed += 1
            else:
                status = "❌ FAIL"
                failed += 1
                failures.append({
                    "question": question,
                    "expected": expected_metric,
                    "actual": actual_metric,
                    "answer": result.get("answer", ""),
                })

            print(f"       Expected: {expected_metric}")
            print(f"       Actual:   {actual_metric}")
            print(f"       {status}")
        except Exception as e:
            status = "❌ ERROR"
            failed += 1
            failures.append({
                "question": question,
                "expected": expected_metric,
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
            print(f"    • Q: {f['question']}")
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