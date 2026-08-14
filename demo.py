"""demo.py — CLI demo for the governed agent (agent_phase2.ask).

Lets you type natural-language questions and see the planner → execute →
synthesize response in real time. Works with Ollama, Gemini, or NVIDIA NIM
(depending on LLM_PROVIDER / .env config).

Usage:
    python demo.py
    LLM_PROVIDER=nvidia python demo.py
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from data_source import DataSource
from agent_phase2 import ask
from llm_provider import get_provider
from config import LLM_PROVIDER
from catalog.service import CatalogService
from metric_factory import merge_auto_metrics_into_catalog


def run_demo():
    provider = get_provider()
    print(f"{'='*60}")
    print(f"  DataAnalytics — Governed Agent CLI Demo")
    print(f"  Provider: {provider.provider_name()}")
    print(f"{'='*60}")
    print()
    print("First, load some data.")
    print("  1. Load sample DataFrame")
    print("  2. Load CSV file (enter path)")
    print("  3. Load SQLite DB (enter path)")
    print()

    choice = input("Choice [1]: ").strip() or "1"

    ds = DataSource()

    if choice == "1":
        import pandas as pd
        df = pd.DataFrame({
            "order_id": [1, 2, 3, 4, 5, 6],
            "customer_id": [10, 10, 20, 30, 30, 40],
            "revenue": [100.0, 200.0, 300.0, 150.0, 250.0, 400.0],
            "quantity": [1, 2, 3, 1, 2, 4],
            "region": ["North", "South", "North", "East", "West", "South"],
            "category": ["A", "B", "A", "C", "B", "A"],
            "order_date": pd.to_datetime(
                ["2024-01-15", "2024-02-20", "2024-03-10", "2024-04-05", "2024-05-12", "2024-06-18"]
            ),
        })
        ds.load_dataframe(df)
        print(f"Loaded sample data: {ds.profile.n_rows} rows x {ds.profile.n_cols} cols")
    elif choice == "2":
        path = input("CSV path: ").strip()
        ds.load_file(path)
        print(f"Loaded: {ds.profile.n_rows} rows x {ds.profile.n_cols} cols")
    elif choice == "3":
        path = input("SQLite DB path: ").strip()
        table = input("Table name [orders_enriched]: ").strip() or "orders_enriched"
        ds.load_sqlite(path, table)
        print(f"Loaded: {ds.profile.n_rows} rows x {ds.profile.n_cols} cols")

    # Seed the governed catalog on first load (auto metrics become approved).
    catalog = CatalogService()
    seeded = merge_auto_metrics_into_catalog(ds, catalog)
    if seeded:
        print(f"Seeded {seeded} auto metrics into the governed catalog.")
    else:
        print("Catalog already populated — using existing approved metrics.")

    print()
    print(f"Schema: {ds.get_schema_card()[:200]}...")
    print(f"Approved metrics: {len(catalog.get_approved_metrics())} available")
    print()
    print("Type a question in plain English (or 'quit' to exit).")
    print()
    print("Examples:")
    print("  - What is the total revenue?")
    print("  - Show me revenue by region")
    print("  - Describe the data")
    print("  - What's the weather today?  (should decline)")
    print()

    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if not question:
            continue

        print()
        try:
            result = ask(question, ds, provider)

            plan_type = result.get("plan", {}).get("plan_type", "?")
            print(f"  Plan: {plan_type}")

            if result.get("confidence") == "n/a":
                print(f"  {result['answer']}")
            else:
                print(f"  Answer: {result['answer']}")
                print(f"  Confidence: {result['confidence']}")
                if result.get("caveats"):
                    for c in result["caveats"]:
                        print(f"  Caveat: {c}")
                if result.get("results"):
                    for r in result["results"]:
                        target = r.get("target", "?")
                        if r.get("error"):
                            print(f"  Step {r.get('step_id', '?')} ({target}): ERROR: {r['error']}")
                        else:
                            val = r.get("result")
                            if hasattr(val, "__len__") and not isinstance(val, str):
                                print(f"  Step {r.get('step_id', '?')} ({target}): {len(val)} rows")
                            else:
                                print(f"  Step {r.get('step_id', '?')} ({target}): {val}")
        except Exception as e:
            print(f"  Error: {e}")
        print()


if __name__ == "__main__":
    run_demo()