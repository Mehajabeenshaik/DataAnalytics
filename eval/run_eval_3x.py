"""eval/run_eval_3x.py — Run the golden-set eval 3 times and report stability.

Runs eval/run_eval.py three times in the same process (same provider,
same questions) and prints all three accuracy percentages together so
you can see if the results are now stable after the temperature fix.
"""
import os
import sys

# Bootstrap .env before any project import
from dotenv import load_dotenv
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the eval function directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_eval import run_eval


def main():
    accuracies = []
    for run_num in range(1, 4):
        print(f"\n{'#'*70}")
        print(f"#  RUN {run_num} OF 3")
        print(f"{'#'*70}\n")
        acc = run_eval()
        accuracies.append(acc)

    print(f"\n{'='*70}")
    print(f"  STABILITY SUMMARY — 3 consecutive runs")
    print(f"{'='*70}")
    for i, acc in enumerate(accuracies, 1):
        print(f"  Run {i}: {acc:.1f}%")
    print(f"  Range: {min(accuracies):.1f}% - {max(accuracies):.1f}%")
    print(f"  Stable: {'YES ✅' if max(accuracies) - min(accuracies) == 0 else 'NO ❌'}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()