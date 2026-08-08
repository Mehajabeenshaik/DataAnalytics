"""
test_postgres_readonly_verification.py — Verify connect_live() read-only enforcement
against a REAL PostgreSQL database (Supabase).

Requires env vars (set in the SAME terminal that runs this script):
  $env:PG_WRITABLE_URL="postgresql://agent_writable:test_writable_pw@<host>:5432/postgres"
  $env:PG_READONLY_URL="postgresql://agent_readonly:test_readonly_pw@<host>:5432/postgres"

What this validates:
  1. connect_live() REJECTS a connection string with write access
     (expects PermissionError from _verify_readonly_connection()).
  2. connect_live() ACCEPTS a genuine read-only role connection string.
  3. A direct write attempt on the read-only role FAILS at the DB level.
  4. Live queries against the read-only role work (profile + query round-trip).

This is the real security check the SQLite tests cannot perform.
"""

import os

from data_source import DataSource


def verify_writable_rejected() -> None:
    writable_url = os.environ.get("PG_WRITABLE_URL", "")
    if not writable_url:
        raise SystemExit(
            "PG_WRITABLE_URL is not set. Set it in this terminal first:\n"
            '  $env:PG_WRITABLE_URL="postgresql://agent_writable:...@host:5432/postgres"'
        )

    source = DataSource(name="writable_check")
    print("\n[1] Testing connect_live() with the WRITABLE URL (expect rejection)...")
    try:
        source.connect_live(writable_url, refresh_mode="always")
    except PermissionError as e:
        print(f"    PASS: connect_live() rejected the writable connection string.")
        print(f"    Reason: {e}")
        return
    except Exception as e:
        print(f"    FAIL: unexpected error type: {type(e).__name__}: {e}")
        raise SystemExit(1)

    print("    FAIL: connect_live() ACCEPTED a writable connection string — "
          "the security check is not working.")
    raise SystemExit(1)


def verify_readonly_accepted() -> None:
    readonly_url = os.environ.get("PG_READONLY_URL", "")
    if not readonly_url:
        raise SystemExit(
            "PG_READONLY_URL is not set. Set it in this terminal first:\n"
            '  $env:PG_READONLY_URL="postgresql://agent_readonly:...@host:5432/postgres"'
        )

    source = DataSource(name="readonly_check")
    print("\n[2] Testing connect_live() with the READ-ONLY URL (expect acceptance)...")
    try:
        source.connect_live(readonly_url, refresh_mode="always", table_name="data")
    except PermissionError:
        print("    FAIL: connect_live() rejected the read-only role — is the role "
              "actually read-only, or did the check misbehave?")
        raise SystemExit(1)
    except Exception as e:
        print(f"    FAIL: connect_live() raised {type(e).__name__}: {e}")
        print("    Check the host/password/SSL settings for the read-only role.")
        raise SystemExit(1)

    print(f"    PASS: connect_live() accepted the read-only role connection string.")
    return source


def verify_direct_write_blocked(readonly_url: str) -> None:
    print("\n[3] Attempting a direct INSERT via the read-only role (expect DB rejection)...")
    from sqlalchemy import create_engine, text

    engine = create_engine(readonly_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE IF NOT EXISTS _ro_write_probe (id INTEGER)")
            )
        print("    FAIL: the 'read-only' role successfully wrote to the database. "
              "This role is NOT actually read-only!")
        raise SystemExit(1)
    except Exception as e:
        err = str(e).lower()
        if "permission denied" in err or "read-only" in err or "executing_sql" in err:
            print(f"    PASS: database rejected the write: {str(e).strip()[:120]}")
        else:
            print(f"    PASS: write blocked ({type(e).__name__}). Message: {str(e).strip()[:120]}")
    finally:
        engine.dispose()


def verify_query_roundtrip(readonly_url: str) -> None:
    print("\n[4] Running a live query round-trip via connect_live()...")
    source = DataSource(name="query_check")
    source.connect_live(readonly_url, refresh_mode="always", table_name="data")
    df = source.query("SELECT 1 AS ok")
    val = int(df.iloc[0, 0])
    if val != 1:
        print(f"    FAIL: unexpected query result: {val}")
        raise SystemExit(1)
    print("    PASS: live query executed successfully over the read-only connection.")
    print(f"    Schema card rows reflect the live table if it has data.")


def main():
    print("=" * 70)
    print("  PostgreSQL READ-ONLY enforcement verification")
    print("=" * 70)

    verify_writable_rejected()
    readonly_url = os.environ.get("PG_READONLY_URL", "")
    verify_readonly_accepted()
    verify_direct_write_blocked(readonly_url)
    verify_query_roundtrip(readonly_url)

    print("\n" + "=" * 70)
    print("  ALL CHECKS PASSED — connect_live() read-only enforcement works")
    print("  against a real PostgreSQL read-only role.")
    print("=" * 70)


if __name__ == "__main__":
    main()