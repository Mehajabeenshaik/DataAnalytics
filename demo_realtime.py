"""
demo_realtime.py — Proves the agent picks up new data without a manual reload.

Default (SQLite):
  Creates a temporary local SQLite DB, connects the agent in "always" refresh mode,
  asks a revenue question, inserts a new fake order directly into the DB (simulating
  a real sale happening), then asks again — and shows the second answer reflects it.

--postgres (real DB):
  Uses the read-only role connection string from the PG_READONLY_URL env var to
  verify connect_live()'s read-only enforcement against a real PostgreSQL database,
  then runs a live Q&A over the read-only connection.

NOTE: agent_phase2.ask() caches responses by question text, so we call
clear_cache() between questions to force a fresh plan + execution.
"""

import argparse
import os
import re
import sqlite3
import tempfile

from agent_phase2 import ask
from cache import clear_cache
from data_source import DataSource
from llm_provider import get_provider


# ── SQLite live-data demo ────────────────────────────────────────────────

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


def main_sqlite() -> None:
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    source = DataSource(name="realtime_demo")
    try:
        print("Setting up test database with 3 initial orders...")
        setup_test_db(db_path)

        provider = get_provider()

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


# ── PostgreSQL read-only verification + live Q&A ─────────────────────────

def main_postgres() -> None:
    readonly_url = os.environ.get("PG_READONLY_URL", "")
    if not readonly_url:
        raise SystemExit(
            "PG_READONLY_URL is not set. Set it in this terminal first:\n"
            '  $env:PG_READONLY_URL="postgresql://agent_readonly:...@host:5432/postgres"'
        )

    writable_url = os.environ.get("PG_WRITABLE_URL", "")
    table_name = os.environ.get("PG_TABLE", "data")

    print("=" * 70)
    print("  PostgreSQL read-only enforcement + live Q&A")
    print("=" * 70)

    # 1. Verify the writable connection string is rejected (if provided).
    if writable_url:
        print("\n[1] Verifying connect_live() REJECTS the writable URL...")
        try:
            probe = DataSource(name="writable_probe")
            probe.connect_live(writable_url, refresh_mode="always")
            print("    FAIL: connect_live() accepted a writable connection string!")
            raise SystemExit(1)
        except PermissionError as e:
            print(f"    PASS: rejected ({e})")
        finally:
            if getattr(probe, "_engine", None) is not None:
                probe._engine.dispose()
    else:
        print("\n[1] PG_WRITABLE_URL not set — skipping the writable-rejection check.")

    # 2. Connect live via the read-only role.
    print(f"\n[2] Connecting live to the read-only role (table: {table_name})...")
    source = DataSource(name="postgres_realtime_demo")
    try:
        source.connect_live(readonly_url, refresh_mode="always", table_name=table_name)
    except Exception as e:
        print(f"    ERROR connecting: {type(e).__name__}: {e}")
        print("    If the table does not exist, create it or set PG_TABLE=<table>.")
        raise SystemExit(1)

    print("    PASS: read-only role accepted and profile built.")
    print("\n    Live schema card:")
    for line in source.get_schema_card().splitlines():
        print(f"      {line}")

    # 3. Run a live Q&A through the agent against Postgres.
    print("\n[3] Asking the agent a live question over the read-only connection...")
    provider = get_provider()
    result = ask("How many rows are in the data set?", source, provider)
    print(f"    Answer: {result['answer']}")
    print(f"    Confidence: {result.get('confidence')}")

    if getattr(source, "_engine", None) is not None:
        source._engine.dispose()

    print("\n" + "=" * 70)
    print("  DONE — read-only connection verified and live query executed.")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Realtime live-data demo")
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Use live PostgreSQL (PG_READONLY_URL) instead of the SQLite demo",
    )
    args = parser.parse_args()

    if args.postgres:
        main_postgres()
    else:
        main_sqlite()


if __name__ == "__main__":
    main()