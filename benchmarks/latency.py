"""benchmarks/latency.py — Phase 0 baseline: plan/execute/synthesize latency split.

Runs GOLDEN_SET questions (imported from eval.run_eval, so the accuracy eval
and the latency benchmark always use the same dataset and question set) against
the active LLM provider and times each phase of agent_phase2 separately:
plan() -> execute_plan() -> synthesize().

This is the baseline every later "vLLM / GPU makes it faster" claim must be
measured against. Run it BEFORE switching providers and save the output,
then run it again with LLM_PROVIDER=vllm and diff the two JSON files — that
diff is the real, publishable number, not a projection.

Usage:
    python benchmarks/latency.py
    python benchmarks/latency.py --n 10                     # first N questions only
    python benchmarks/latency.py --out benchmarks/results/baseline.json
    LLM_PROVIDER=vllm python benchmarks/latency.py --out benchmarks/results/vllm.json
"""
import argparse
import json
import os
import statistics
import sys
import time

# Add backend/app to path (modules moved during frontend/backend restructure)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "app"))

from dotenv import load_dotenv
load_dotenv()

from agent_phase2 import plan, execute_plan, synthesize
from llm_provider import get_provider, LLMProvider
from eval.run_eval import GOLDEN_SET, _make_eval_ds


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile — no numpy dependency needed for this."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def run_benchmark(
    n: int | None = None,
    provider: LLMProvider | None = None,
    ds=None,
) -> tuple[dict[str, list[float]], int, str, int]:
    """Time plan/execute/synthesize separately across GOLDEN_SET questions.

    Declined questions (can_answer=False) only contribute to "plan" and
    "total" — there's no execute/synthesize phase to time for them, and
    counting a zero there would silently drag down those phases' means.

    Returns (timings_by_phase_in_seconds, error_count, provider_name, n_questions).
    """
    provider = provider or get_provider()
    ds = ds if ds is not None else _make_eval_ds()
    questions = [q for q, _ in GOLDEN_SET]
    if n:
        questions = questions[:n]

    timings: dict[str, list[float]] = {"plan": [], "execute": [], "synthesize": [], "total": []}
    errors = 0

    for q in questions:
        t0 = time.perf_counter()
        try:
            the_plan = plan(q, ds, provider)
            t1 = time.perf_counter()
            timings["plan"].append(t1 - t0)

            if not the_plan.can_answer:
                timings["total"].append(t1 - t0)
                continue

            results = execute_plan(the_plan, ds)
            t2 = time.perf_counter()
            timings["execute"].append(t2 - t1)

            synthesize(q, the_plan, results, provider)
            t3 = time.perf_counter()
            timings["synthesize"].append(t3 - t2)

            timings["total"].append(t3 - t0)
        except Exception as e:  # noqa: BLE001 — a benchmark run should finish, not crash
            errors += 1
            print(f"  ERROR on '{q}': {e}")

    return timings, errors, provider.provider_name(), len(questions)


def print_report(timings: dict, errors: int, provider_name: str, n_questions: int) -> None:
    print("=" * 70)
    print("  Latency Benchmark — agent_phase2 (plan / execute / synthesize)")
    print(f"  Provider: {provider_name}")
    print(f"  Questions: {n_questions}  (errors: {errors})")
    print("=" * 70)
    header = f"{'Phase':<12}{'n':>5}{'mean(ms)':>12}{'p50(ms)':>12}{'p95(ms)':>12}"
    print(header)
    print("-" * len(header))
    for phase in ("plan", "execute", "synthesize", "total"):
        vals = [v * 1000 for v in timings[phase]]
        if not vals:
            print(f"{phase:<12}{0:>5}{'-':>12}{'-':>12}{'-':>12}")
            continue
        mean = statistics.mean(vals)
        p50 = _percentile(vals, 50)
        p95 = _percentile(vals, 95)
        print(f"{phase:<12}{len(vals):>5}{mean:>12.1f}{p50:>12.1f}{p95:>12.1f}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=None, help="Limit to first N golden-set questions")
    parser.add_argument("--out", type=str, default=None, help="Write raw timings to this JSON file")
    args = parser.parse_args()

    timings, errors, provider_name, n_questions = run_benchmark(n=args.n)
    print_report(timings, errors, provider_name, n_questions)

    if args.out:
        out_dir = os.path.dirname(args.out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(
                {
                    "provider": provider_name,
                    "n_questions": n_questions,
                    "errors": errors,
                    "timings_seconds": timings,
                },
                f,
                indent=2,
            )
        print(f"Raw timings written to {args.out}")


if __name__ == "__main__":
    main()