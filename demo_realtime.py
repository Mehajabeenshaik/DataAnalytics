"""
demo_realtime.py — Proves the agent picks up new data without a manual reload.

Creates a temporary local SQLite DB, connects the agent in "always" refresh mode,
asks a revenue question, inserts a new fake order directly into the DB (simulating
a real sale happening), then asks again — and shows the second answer reflects it.

NOTE: agent_phase2.ask() caches responses by question text, so we call
clear_cache() between the two questions to force a fresh plan + execution.
"""

import os
import re
import sqlite3
import tempfile

from agent_phase2 import ask
from cache import clear_cache
from data_source import DataSource
from llm_provider import get_provider


def setup_test_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE data (
            order_id INTEGER PRIMARY KEY,
            order_date TEXT,
            total_amount REAL,
            order_status TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO data VALUES (?,?,?,?)",
        [
            (1, "2026-08-01", 1000.0, "completed"),
            (2, "2026-08-02", 1500.0, "completed"),
            (3, "2026-08-03", 2000.0, "completed"),
        ],
    )
    conn.commit()
    conn.close()


def insert_new_order(db_path: str) -> None:
    """Simulates a new real sale happening while the agent is running."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO data VALUES (?,?,?,?)",
        (4, "2026-08-04", 5000.0, "completed"),
    )
    conn.commit()
    conn.close()


def _extract_number(text: str) -> float:
    """Pull the first number out of an answer string."""
    match = re.search(r"[\d,]+\.?\d*", text)
    if not match:
        raise ValueError(f"Could not find a number in answer: {text!r}")
    return float(match.group().replace(",", ""))


def main():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    try:
        print("Setting up test database with 3 initial orders...")
        setup_test_db(db_path)

        provider = get_provider()

        source = DataSource(name="realtime_demo")
        # SQLite has no real read-only role mechanism, so this demo uses a plain
        # connection string — the _verify_readonly_connection() check is meant
        # for Postgres/MySQL with an actual read-only role. Note this limitation
        # clearly for anyone adapting this demo to SQLite in production.
        source.connect_live(f"sqlite:///{db_path}", refresh_mode="always")

        print("\n--- Question 1 (before new order) ---")
        result_1 = ask("What is our total revenue?", source, provider)
        print(f"Answer: {result_1['answer']}")

        print("\nInserting a new $5000 order directly into the database "
              "(simulating a real sale happening)...")
        insert_new_order(db_path)

        # ask() caches by question text — clear it so the second ask re-queries.
        clear_cache()

        print("\n--- Question 2 (same question, after new order) ---")
        result_2 = ask("What is our total revenue?", source, provider)
        print(f"Answer: {result_2['answer']}")

        num_1 = _extract_number(result_1["answer"])
        num_2 = _extract_number(result_2["answer"])

        assert num_2 > num_1, (
            f"FAILED: expected revenue to increase after the new order, "
            f"got {num_1} then {num_2} — the agent is NOT reading live data."
        )
        print(f"\n[OK] CONFIRMED LIVE: revenue went from {num_1} to {num_2} "
              f"without any manual data reload.")

    finally:
        # Dispose the SQLAlchemy engine so the SQLite file is released (Windows).
        if getattr(source, "_engine", None) is not None:
            source._engine.dispose()
        try:
            os.remove(db_path)
        except PermissionError:
            import time as _time
            _time.sleep(0.2)
            os.remove(db_path)


if __name__ == "__main__":
    main()