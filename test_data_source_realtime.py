import os
import sqlite3
import tempfile
import time

import pytest

from data_source import DataSource


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, amount REAL)")
    conn.execute("INSERT INTO data VALUES (1, 100.0)")
    conn.commit()
    conn.close()
    yield path
    # Dispose any SQLAlchemy engine that may still hold the file open (Windows).
    import gc
    gc.collect()
    try:
        os.remove(path)
    except PermissionError:
        # Engine may still hold a connection; retry after a brief pause.
        import time as _time
        _time.sleep(0.2)
        os.remove(path)


def insert_row(db_path: str, id_: int, amount: float):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO data VALUES (?, ?)", (id_, amount))
    conn.commit()
    conn.close()


def test_always_mode_reflects_new_data_immediately(temp_db):
    source = DataSource(name="test_always")
    source.connect_live(f"sqlite:///{temp_db}", refresh_mode="always")

    before = source.query("SELECT SUM(amount) as total FROM data")
    assert before["total"].iloc[0] == 100.0

    insert_row(temp_db, 2, 500.0)

    after = source.query("SELECT SUM(amount) as total FROM data")
    assert after["total"].iloc[0] == 600.0  # picked up the new row immediately


def test_ttl_mode_caches_within_window(temp_db):
    source = DataSource(name="test_ttl")
    source.connect_live(f"sqlite:///{temp_db}", refresh_mode="ttl", ttl_seconds=5)

    before = source.query("SELECT SUM(amount) as total FROM data")
    assert before["total"].iloc[0] == 100.0

    insert_row(temp_db, 2, 500.0)

    # Within the TTL window — should still return the CACHED (stale) value
    still_cached = source.query("SELECT SUM(amount) as total FROM data")
    assert still_cached["total"].iloc[0] == 100.0, (
        "Expected cached value within TTL window, but got fresh data — "
        "caching is not working correctly."
    )


def test_ttl_mode_refreshes_after_expiry(temp_db):
    source = DataSource(name="test_ttl_expiry")
    source.connect_live(f"sqlite:///{temp_db}", refresh_mode="ttl", ttl_seconds=1)

    source.query("SELECT SUM(amount) as total FROM data")  # populate cache
    insert_row(temp_db, 2, 500.0)

    time.sleep(1.2)  # wait past the TTL

    after = source.query("SELECT SUM(amount) as total FROM data")
    assert after["total"].iloc[0] == 600.0, (
        "Expected fresh data after TTL expiry, but got stale cached value."
    )


def test_static_mode_still_works_unchanged(temp_db):
    """Regression check: connect_live() must not break the existing static path."""
    source = DataSource(name="test_static")
    source.load_sqlite(temp_db, query="SELECT * FROM data")
    assert source.is_live() is False
    result = source.query("SELECT SUM(amount) as total FROM data")
    assert result["total"].iloc[0] == 100.0


def test_invalid_refresh_mode_rejected(temp_db):
    source = DataSource(name="test_invalid_mode")
    with pytest.raises(ValueError, match="refresh_mode"):
        source.connect_live(f"sqlite:///{temp_db}", refresh_mode="bogus")