"""
Tests for DataSource live-connection (connect_live) functionality.

Coverage:
  - SQLite always/ttl/expiry/static modes (regression, unchanged)
  - Dialect detection helper
  - Engine kwargs helper (timeout configuration)
  - Postgres read-only acceptance  — mocked engine (no real DB required)
  - Postgres writable rejection     — mocked engine
  - MySQL read-only acceptance      — mocked engine
  - MySQL writable rejection        — mocked engine
  - Generic dialect writable rejection
  - Connection error surfaces correctly (not swallowed)
  - Invalid refresh_mode rejected
"""

import os
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock, patch, call

import pytest

from data_source import DataSource, _dialect_from_url, _engine_kwargs_for_dialect


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Temporary SQLite DB with one row of data."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, amount REAL)")
    conn.execute("INSERT INTO data VALUES (1, 100.0)")
    conn.commit()
    conn.close()
    yield path
    import gc
    gc.collect()
    try:
        os.remove(path)
    except PermissionError:
        time.sleep(0.2)
        os.remove(path)


def insert_row(db_path: str, id_: int, amount: float) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO data VALUES (?, ?)", (id_, amount))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Helpers to build a mock SQLAlchemy engine that behaves like read-only or
# writable Postgres/MySQL, without requiring a real database.
# ---------------------------------------------------------------------------

def _make_writable_engine(dialect_name: str = "postgresql"):
    """Return a mock engine whose DDL probe succeeds (writable — bad)."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value = None                  # DDL succeeds
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_conn_autocommit = MagicMock()
    mock_conn_autocommit.execute.return_value = None
    mock_conn_autocommit.__enter__ = MagicMock(return_value=mock_conn_autocommit)
    mock_conn_autocommit.__exit__ = MagicMock(return_value=False)
    mock_conn_autocommit.execution_options = MagicMock(return_value=mock_conn_autocommit)

    engine = MagicMock()
    engine.url = MagicMock()
    engine.url.__str__ = lambda s: f"{dialect_name}://user:pass@host/db"
    engine.connect.return_value = mock_conn_autocommit
    engine.begin.return_value = mock_conn
    return engine


def _make_readonly_engine(
    dialect_name: str = "postgresql",
    ddl_exc: Exception | None = None,
):
    """Return a mock engine whose DDL probe raises an exception (read-only — good).

    ``ddl_exc`` is the exception raised when DDL is attempted; defaults to a
    Postgres-flavoured permission-denied error.
    """
    if ddl_exc is None:
        ddl_exc = Exception("ERROR: cannot execute CREATE TABLE in a read-only transaction")

    mock_conn_autocommit = MagicMock()
    mock_conn_autocommit.execute.return_value = None
    mock_conn_autocommit.__enter__ = MagicMock(return_value=mock_conn_autocommit)
    mock_conn_autocommit.__exit__ = MagicMock(return_value=False)
    mock_conn_autocommit.execution_options = MagicMock(return_value=mock_conn_autocommit)

    mock_conn_begin = MagicMock()
    mock_conn_begin.execute.side_effect = ddl_exc
    mock_conn_begin.__enter__ = MagicMock(return_value=mock_conn_begin)
    mock_conn_begin.__exit__ = MagicMock(return_value=False)

    engine = MagicMock()
    engine.url = MagicMock()
    engine.url.__str__ = lambda s: f"{dialect_name}://user:pass@host/db"
    engine.connect.return_value = mock_conn_autocommit
    engine.begin.return_value = mock_conn_begin
    return engine


# ---------------------------------------------------------------------------
# Existing SQLite tests (regression — must stay green and unchanged in
# behaviour relative to the original implementation)
# ---------------------------------------------------------------------------

class TestSQLiteRegressions:
    def test_always_mode_reflects_new_data_immediately(self, temp_db):
        source = DataSource(name="test_always")
        source.connect_live(f"sqlite:///{temp_db}", refresh_mode="always")

        before = source.query("SELECT SUM(amount) as total FROM data")
        assert before["total"].iloc[0] == 100.0

        insert_row(temp_db, 2, 500.0)

        after = source.query("SELECT SUM(amount) as total FROM data")
        assert after["total"].iloc[0] == 600.0

    def test_ttl_mode_caches_within_window(self, temp_db):
        source = DataSource(name="test_ttl")
        source.connect_live(f"sqlite:///{temp_db}", refresh_mode="ttl", ttl_seconds=5)

        before = source.query("SELECT SUM(amount) as total FROM data")
        assert before["total"].iloc[0] == 100.0

        insert_row(temp_db, 2, 500.0)

        still_cached = source.query("SELECT SUM(amount) as total FROM data")
        assert still_cached["total"].iloc[0] == 100.0, (
            "Expected cached value within TTL window, but got fresh data — "
            "caching is not working correctly."
        )

    def test_ttl_mode_refreshes_after_expiry(self, temp_db):
        source = DataSource(name="test_ttl_expiry")
        source.connect_live(f"sqlite:///{temp_db}", refresh_mode="ttl", ttl_seconds=1)

        source.query("SELECT SUM(amount) as total FROM data")  # populate cache
        insert_row(temp_db, 2, 500.0)

        time.sleep(1.2)  # wait past the TTL

        after = source.query("SELECT SUM(amount) as total FROM data")
        assert after["total"].iloc[0] == 600.0, (
            "Expected fresh data after TTL expiry, but got stale cached value."
        )

    def test_static_mode_still_works_unchanged(self, temp_db):
        """Regression check: connect_live() must not break the existing static path."""
        source = DataSource(name="test_static")
        source.load_sqlite(temp_db, query="SELECT * FROM data")
        assert source.is_live() is False
        result = source.query("SELECT SUM(amount) as total FROM data")
        assert result["total"].iloc[0] == 100.0

    def test_invalid_refresh_mode_rejected(self, temp_db):
        source = DataSource(name="test_invalid_mode")
        with pytest.raises(ValueError, match="refresh_mode"):
            source.connect_live(f"sqlite:///{temp_db}", refresh_mode="bogus")

    def test_sqlite_skips_readonly_check(self, temp_db):
        """SQLite connect_live must not raise even though SQLite is writable."""
        source = DataSource(name="test_sqlite_skip")
        # Should not raise — SQLite path is always skipped.
        source.connect_live(f"sqlite:///{temp_db}", refresh_mode="always")
        assert source.is_live() is True


# ---------------------------------------------------------------------------
# Dialect detection helper
# ---------------------------------------------------------------------------

class TestDialectDetection:
    @pytest.mark.parametrize("url,expected", [
        ("postgresql://user:pass@host/db",           "postgresql"),
        ("postgresql+psycopg2://user:pass@host/db",  "postgresql"),
        ("postgres://user:pass@host/db",             "postgresql"),
        ("mysql://user:pass@host/db",                "mysql"),
        ("mysql+pymysql://user:pass@host/db",        "mysql"),
        ("mariadb+mariadbconnector://host/db",       "mysql"),
        ("sqlite:///path/to/file.db",                "sqlite"),
        ("mssql+pyodbc://user:pass@dsn",             "mssql"),
    ])
    def test_dialect_from_url(self, url, expected):
        assert _dialect_from_url(url) == expected


# ---------------------------------------------------------------------------
# Engine kwargs (timeout configuration)
# ---------------------------------------------------------------------------

class TestEngineKwargs:
    def test_postgres_gets_connect_timeout_and_statement_timeout(self):
        kwargs = _engine_kwargs_for_dialect("postgresql")
        assert "connect_args" in kwargs
        assert "connect_timeout" in kwargs["connect_args"]
        assert "options" in kwargs["connect_args"]
        assert "statement_timeout" in kwargs["connect_args"]["options"]

    def test_mysql_gets_connect_timeout(self):
        kwargs = _engine_kwargs_for_dialect("mysql")
        assert "connect_args" in kwargs
        assert "connect_timeout" in kwargs["connect_args"]

    def test_sqlite_gets_no_extra_kwargs(self):
        kwargs = _engine_kwargs_for_dialect("sqlite")
        assert kwargs == {}

    def test_unknown_dialect_gets_no_extra_kwargs(self):
        kwargs = _engine_kwargs_for_dialect("mssql")
        assert kwargs == {}


# ---------------------------------------------------------------------------
# Postgres read-only enforcement
# ---------------------------------------------------------------------------

class TestPostgresReadOnlyEnforcement:
    def test_readonly_postgres_accepted(self):
        """A Postgres connection that rejects DDL should be accepted."""
        source = DataSource(name="test_pg_ro_ok")
        source._engine = _make_readonly_engine(
            dialect_name="postgresql",
            ddl_exc=Exception("ERROR: cannot execute CREATE TABLE in a read-only transaction"),
        )
        # Should not raise
        source._verify_readonly_postgres()

    def test_readonly_postgres_permission_denied_accepted(self):
        """permission denied for CREATE TABLE is also a valid read-only signal."""
        source = DataSource(name="test_pg_perm")
        source._engine = _make_readonly_engine(
            dialect_name="postgresql",
            ddl_exc=Exception("permission denied for schema public"),
        )
        source._verify_readonly_postgres()  # must not raise

    def test_writable_postgres_rejected(self):
        """A Postgres connection that allows DDL must be rejected."""
        source = DataSource(name="test_pg_writable")
        source._engine = _make_writable_engine(dialect_name="postgresql")
        with pytest.raises(PermissionError, match="connect_live\\(\\) refused"):
            source._verify_readonly_postgres()

    def test_writable_postgres_error_mentions_fix(self):
        """The PermissionError message must include actionable fix instructions."""
        source = DataSource(name="test_pg_msg")
        source._engine = _make_writable_engine(dialect_name="postgresql")
        with pytest.raises(PermissionError) as exc_info:
            source._verify_readonly_postgres()
        msg = str(exc_info.value)
        assert "GRANT SELECT" in msg
        assert "analytics_ro" in msg

    def test_connection_error_surfaces_not_swallowed(self):
        """A genuine connection failure (e.g. wrong host) must not be silently ignored."""
        source = DataSource(name="test_pg_conn_err")
        source._engine = _make_readonly_engine(
            dialect_name="postgresql",
            ddl_exc=Exception("could not connect to server: Connection refused"),
        )
        with pytest.raises(ConnectionError, match="could not verify Postgres read-only status"):
            source._verify_readonly_postgres()

    def test_verify_readonly_connection_dispatches_postgres(self):
        """_verify_readonly_connection should call the Postgres-specific method."""
        source = DataSource(name="test_dispatch_pg")
        source._engine = _make_readonly_engine()
        with patch.object(source, "_verify_readonly_postgres") as mock_pg:
            source._verify_readonly_connection(dialect="postgresql")
            mock_pg.assert_called_once()

    def test_verify_readonly_connection_dispatches_postgres_alias(self):
        """'postgres' dialect alias also routes to the Postgres method."""
        source = DataSource(name="test_dispatch_alias")
        source._engine = _make_readonly_engine()
        with patch.object(source, "_verify_readonly_postgres") as mock_pg:
            source._verify_readonly_connection(dialect="postgres")
            mock_pg.assert_called_once()


# ---------------------------------------------------------------------------
# MySQL read-only enforcement
# ---------------------------------------------------------------------------

class TestMySQLReadOnlyEnforcement:
    def test_readonly_mysql_accepted(self):
        """A MySQL connection that rejects DDL should be accepted."""
        source = DataSource(name="test_mysql_ro_ok")
        source._engine = _make_readonly_engine(
            dialect_name="mysql",
            ddl_exc=Exception("1792: Cannot execute statement in a READ ONLY transaction"),
        )
        source._verify_readonly_mysql()  # must not raise

    def test_writable_mysql_rejected(self):
        """A MySQL connection that allows DDL must be rejected."""
        source = DataSource(name="test_mysql_writable")
        source._engine = _make_writable_engine(dialect_name="mysql")
        with pytest.raises(PermissionError, match="connect_live\\(\\) refused"):
            source._verify_readonly_mysql()

    def test_writable_mysql_error_mentions_fix(self):
        """The PermissionError message must include actionable fix instructions."""
        source = DataSource(name="test_mysql_msg")
        source._engine = _make_writable_engine(dialect_name="mysql")
        with pytest.raises(PermissionError) as exc_info:
            source._verify_readonly_mysql()
        msg = str(exc_info.value)
        assert "GRANT SELECT" in msg
        assert "analytics_ro" in msg

    def test_mysql_connection_error_surfaces(self):
        """Genuine MySQL connection failure must not be silently ignored."""
        source = DataSource(name="test_mysql_conn_err")
        source._engine = _make_readonly_engine(
            dialect_name="mysql",
            ddl_exc=Exception("Can't connect to MySQL server on 'host'"),
        )
        with pytest.raises(ConnectionError, match="could not verify MySQL read-only status"):
            source._verify_readonly_mysql()

    def test_verify_readonly_connection_dispatches_mysql(self):
        """_verify_readonly_connection should call the MySQL-specific method."""
        source = DataSource(name="test_dispatch_mysql")
        source._engine = _make_readonly_engine(dialect_name="mysql")
        with patch.object(source, "_verify_readonly_mysql") as mock_mysql:
            source._verify_readonly_connection(dialect="mysql")
            mock_mysql.assert_called_once()

    def test_verify_readonly_connection_dispatches_mariadb(self):
        """'mariadb' dialect also routes to the MySQL method."""
        source = DataSource(name="test_dispatch_mariadb")
        source._engine = _make_readonly_engine(dialect_name="mysql")
        with patch.object(source, "_verify_readonly_mysql") as mock_mysql:
            source._verify_readonly_connection(dialect="mariadb")
            mock_mysql.assert_called_once()


# ---------------------------------------------------------------------------
# Generic dialect fallback
# ---------------------------------------------------------------------------

class TestGenericDialectEnforcement:
    def test_writable_generic_rejected(self):
        """Other dialects that allow DDL must also be rejected."""
        source = DataSource(name="test_generic_writable")
        source._engine = _make_writable_engine(dialect_name="mssql")
        with pytest.raises(PermissionError, match="WRITE"):
            source._verify_readonly_generic()

    def test_readonly_generic_accepted(self):
        """Other dialects that reject DDL must be accepted."""
        source = DataSource(name="test_generic_ro")
        source._engine = _make_readonly_engine(
            dialect_name="mssql",
            ddl_exc=Exception("The user does not have permission"),
        )
        source._verify_readonly_generic()  # must not raise


# ---------------------------------------------------------------------------
# SQLite skips check
# ---------------------------------------------------------------------------

class TestSQLiteSkipsBehavior:
    def test_sqlite_dialect_skips_all_checks(self):
        """The read-only check must be a no-op for SQLite."""
        source = DataSource(name="test_sqlite_noop")
        # Engine that would raise PermissionError if probed
        source._engine = _make_writable_engine(dialect_name="sqlite")
        # Should not raise
        source._verify_readonly_connection(dialect="sqlite")

    def test_none_engine_is_safe(self):
        """_verify_readonly_connection with no engine set must be a no-op."""
        source = DataSource(name="test_no_engine")
        source._engine = None
        source._verify_readonly_connection(dialect="postgresql")  # must not raise