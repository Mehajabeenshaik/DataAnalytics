"""demo.py — CLI demo for the governed agent (agent_phase2.ask).

Lets you type natural-language questions and see the planner → execute →
synthesize response in real time. Works with Ollama, Gemini, or NVIDIA NIM
(depending on LLM_PROVIDER / .env config).

Supports loading multiple named datasets and switching between them with
the `use <name>` command. Example:

    python demo.py
    > load 2                    # load a CSV file
    > load 1                    # load the sample DataFrame
    > use sample_dataframe      # switch to the sample dataset
    > What is total revenue?
"""
import os

from dotenv import load_dotenv
load_dotenv()

from data_source import DataSource
from dataset_registry import DatasetRegistry
from agent_phase2 import ask
from llm_provider import get_provider
from catalog.service import CatalogService
from metric_factory import merge_auto_metrics_into_catalog


def _load_dataset(choice: str) -> tuple[DataSource, str]:
    """Load a dataset based on the user's choice. Returns (ds, display_name)."""
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
        return ds, "sample_dataframe"
    if choice == "2":
        path = input("CSV path: ").strip()
        ds.load_file(path)
        print(f"Loaded: {ds.profile.n_rows} rows x {ds.profile.n_cols} cols")
        # Use the file stem (lowercase) as the dataset name for `use`.
        return ds, os.path.splitext(os.path.basename(path))[0].lower()
    if choice == "3":
        path = input("SQLite DB path: ").strip()
        table = input("Table name [orders_enriched]: ").strip() or "orders_enriched"
        ds.load_sqlite(path, table)
        print(f"Loaded: {ds.profile.n_rows} rows x {ds.profile.n_cols} cols")
        return ds, table.lower()

    raise ValueError(f"Unknown choice: {choice}")


def run_demo():
    provider = get_provider()
    registry = DatasetRegistry()

    print(f"{'='*60}")
    print("  DataAnalytics — Governed Agent CLI Demo")
    print(f"  Provider: {provider.provider_name()}")
    print(f"{'='*60}")
    print()
    print("Load data (you can load more than one file and switch with `use <name>`).")
    print("  1. Load sample DataFrame")
    print("  2. Load CSV file (enter path)")
    print("  3. Load SQLite DB (enter path)")
    print("  (or blank to skip and just ask questions)")
    print()

    choice = input("Choice [1]: ").strip() or "1"

    if choice:
        try:
            ds, name = _load_dataset(choice)
            registry.add(name=name, ds=ds, make_default=True)

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
            print(f"Dataset '{name}' is now the default.")
        except Exception as e:
            print(f"Failed to load initial data: {e}")

    print()
    print("Commands:")
    print("  load 1 | 2 | 3   — load another dataset (sample / CSV / SQLite)")
    print("  use <name>       — switch the active dataset")
    print("  datasets         — list all loaded datasets")
    print("  quit             — exit")
    print()
    print("Type a question in plain English to ask the agent.")
    print()
    print("Examples:")
    print("  - What is the total revenue?")
    print("  - Show me revenue by region")
    print("  - Describe the data")
    print("  - What's the weather today?  (should decline)")
    print()

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not line:
            continue

        low = line.lower()

        if low in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        # ── Multi-dataset commands ──────────────────────────────────────
        if low.startswith("load "):
            try:
                ds, name = _load_dataset(low[5:].strip())
            except Exception as e:
                print(f"  Error: {e}")
                continue

            # Seed catalog for the newly loaded dataset so its metrics exist.
            try:
                catalog = CatalogService()
                seeded = merge_auto_metrics_into_catalog(ds, catalog)
                if seeded:
                    print(f"  Seeded {seeded} auto metrics for '{name}'.")
            except Exception as e:
                print(f"  Catalog seed warning: {e}")

            was_empty = len(registry) == 0
            registry.add(name=name, ds=ds, make_default=was_empty)
            print(f"  Added dataset '{name}' ({ds.profile.n_rows} rows x {ds.profile.n_cols} cols).")
            if was_empty:
                print(f"  '{name}' is now the default dataset.")
            else:
                print(f"  Switch to it with: use {name}")
            continue

        if low.startswith("use "):
            target = low[4:].strip()
            if not registry.has(target):
                print(f"  Unknown dataset '{target}'. Available: {registry.list_names()}")
                continue
            # re-add as default without changing the DataSource object
            ds = registry.get(target)
            registry.add(name=target, ds=ds, make_default=True)
            print(f"  Switched to dataset '{target}'.")
            continue

        if low in ("datasets", "list", "ls"):
            print(f"  Datasets: {registry.list_names()}")
            print(f"  Default:  {registry.default_name}")
            continue

        # ── Ask the agent ───────────────────────────────────────────────
        if len(registry) == 0:
            print("  No data loaded. Use `load 1`, `load 2`, or `load 3` first.")
            continue

        ds = registry.get()
        print()
        try:
            result = ask(
                question=line,
                ds=ds,
                provider=provider,
                dataset_names=registry.list_names(),
            )

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