"""
DataSource abstraction — supports local files (CSV/Parquet), DataFrames, and SQLite.
All analysis goes through a single registered DuckDB source.

PII Protection:
  After loading, any column whose sample values trigger Presidio detections
  (PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION) is automatically masked
  via pii_masker.PIIMasker before the data becomes queryable. The original
  values are stored in the encrypted PII vault; only masked tokens appear
  in the DuckDB table and in the schema card sent to the LLM.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from cachetools import TTLCache
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Connection timeout defaults (seconds).  Applied at engine-creation time
# so a misconfigured or unreachable host never hangs the agent indefinitely.
# ---------------------------------------------------------------------------
_CONNECT_TIMEOUT_POSTGRES = 10   # seconds
_CONNECT_TIMEOUT_MYSQL = 10      # seconds
_STATEMENT_TIMEOUT_POSTGRES = 30_000  # milliseconds (statement_timeout GUC)


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    n_unique: int | None = None
    n_null: int = 0
    examples: list[Any] = Field(default_factory=list)
    is_numeric: bool = False
    is_temporal: bool = False
    is_categorical: bool = False
    description: str = ""


class TableProfile(BaseModel):
    name: str
    n_rows: int
    n_cols: int
    columns: list[ColumnProfile]
    sample_rows: list[dict] = Field(default_factory=list)


class DataSource:
    """Single source of truth for the agent."""

    def __init__(self, name: str = "main"):
        self.name = name
        self.con = duckdb.connect(database=":memory:")
        self.table_name = "data"
        self.profile: TableProfile | None = None
        self._allowed_filter_columns: list[str] = []
        self._metrics_cache: dict | None = None
        self._pii_masked_columns: set[str] = set()
        self._instance_id = uuid.uuid4().hex

        # Live-connection state (set by connect_live())
        self._is_live = False
        self._engine = None
        self._refresh_mode = "ttl"
        self._live_table_name = "data"
        self._query_cache: TTLCache | None = None
        self._cache_lock = threading.Lock()

    # ── PII detection + masking ────────────────────────────────────────────

    def _detect_and_mask_pii(self, df: pd.DataFrame) -> pd.DataFrame:
        """Detect PII columns via column-name heuristics + Presidio and mask them.

        Column-name heuristics are the PRIMARY PII signal — they are robust and
        avoid false positives on legitimate categoricals (e.g. "region" with
        values North/South/East/West that Presidio flags as LOCATION). Presidio
        value detection is a secondary layer for columns whose names don't hint
        at PII but whose values contain PERSON/EMAIL/PHONE entities.

        Returns the (possibly modified) DataFrame.
        """
        try:
            from pii_masker import PIIMasker
        except ImportError:
            return df

        masker = PIIMasker()
        from pii_masker import _get_analyzer as _get_pii_analyzer
        analyzer = _get_pii_analyzer()
        if analyzer is None:
            return df

        df = df.copy()
        # Column-name keywords that strongly indicate PII.
        PII_NAME_KEYWORDS = (
            "email", "phone", "name", "address", "ssn", "credit", "card",
            "password", "dob", "birth", "social", "account",
        )
        # Value-based entities. LOCATION is intentionally excluded to avoid
        # flagging legitimate categoricals like region = North/South/East/West.
        pii_entities = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                continue

            col_lower = col.lower()
            has_pii = any(k in col_lower for k in PII_NAME_KEYWORDS)

            if not has_pii:
                samples = df[col].dropna().astype(str).head(20).tolist()
                if samples:
                    for sample in samples:
                        detections = analyzer.analyze(
                            text=sample, entities=pii_entities, language="en"
                        )
                        if detections:
                            has_pii = True
                            break

            if has_pii:
                df[col] = df[col].apply(
                    lambda v: self._mask_value(col, v, masker) if pd.notna(v) else v
                )
                self._pii_masked_columns.add(col)

        if self._pii_masked_columns:
            print(
                f"PII: Masked columns: {sorted(self._pii_masked_columns)}"
            )

        return df

    @staticmethod
    def _mask_value(col_name: str, value, masker) -> str:
        """Mask a single PII value using Presidio + tokenisation."""
        if not isinstance(value, str):
            value = str(value)

        col_lower = col_name.lower()
        if "email" in col_lower:
            return "customer.masked@masked.local"
        elif "phone" in col_lower:
            return "+91-XXXXX-XXXXX"
        elif "name" in col_lower:
            return "Customer [REDACTED]"
        elif "address" in col_lower:
            return "[REDACTED]"
        else:
            detections = masker.scan_text(value)
            if detections:
                return "[REDACTED - possible PII detected]"
            return value

    # ── Loading methods ────────────────────────────────────────────────────

    def load_file(self, path: str | Path, table_name: str = "data") -> None:
        path = Path(path)
        self.table_name = table_name

        if path.suffix.lower() in {".csv", ".tsv"}:
            sep = "\t" if path.suffix.lower() == ".tsv" else ","
            try:
                df = pd.read_csv(path, encoding="utf-8", sep=sep)
            except UnicodeDecodeError as exc:
                raise UnicodeDecodeError(
                    exc.encoding or "utf-8",
                    exc.object,
                    exc.start,
                    exc.end,
                    "This file is not UTF-8 encoded. Please re-save as CSV UTF-8 and try again.",
                ) from exc
        elif path.suffix.lower() in {".parquet", ".pq"}:
            df = pd.read_parquet(path)
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
        elif path.suffix.lower() == ".json":
            df = pd.read_json(path)
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")


        df = self._detect_and_mask_pii(df)
        self.load_dataframe(df, table_name)

    def load_dataframe(self, df: pd.DataFrame, table_name: str = "data") -> None:
        self.table_name = table_name
        df = df.copy()
        df = self._detect_and_mask_pii(df)
        for col in df.columns:
            if df[col].dtype == "string" or str(df[col].dtype).startswith("str"):
                df[col] = df[col].astype("object")
        self.con.register("tmp_df", df)
        self.con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM tmp_df")
        self.con.unregister("tmp_df")
        self._build_profile()

    def load_sqlite(self, db_path: str, query: str = "SELECT * FROM orders_enriched") -> None:
        """Bridge to an existing SQLite database."""
        import re

        norm_path = db_path.replace("\\", "/")

        try:
            self.con.execute(f"ATTACH '{norm_path}' AS src (TYPE SQLITE)")

            stripped = query.strip()
            if not re.search(r"\s", stripped):
                safe_query = f"SELECT * FROM src.{stripped}"
            elif re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
                safe_query = re.sub(
                    r"(\bFROM\s+|\bJOIN\s+)([A-Za-z_][A-Za-z0-9_]*)",
                    r"\1src.\2",
                    stripped,
                )
            else:
                safe_query = f"SELECT * FROM src.{stripped}"

            self.con.execute(f"CREATE OR REPLACE TABLE data AS {safe_query}")
            self.table_name = "data"
            self._build_profile()
        except Exception:
            import sqlite3

            conn = sqlite3.connect(db_path)
            df = pd.read_sql_query(query, conn)
            conn.close()
            df = self._detect_and_mask_pii(df)
            self.load_dataframe(df, "data")

    # ── Live connection (read-only DB) ─────────────────────────────────────

    def connect_live(
        self,
        connection_string: str,
        refresh_mode: str = "ttl",
        ttl_seconds: int = 30,
        table_name: str = "data",
    ) -> None:
        """Connect to a LIVE, read-only database instead of loading a static snapshot.

        The connection_string MUST point to a read-only database role/user.
        This method actively verifies the read-only constraint and raises
        ``PermissionError`` with a clear, actionable message if the credentials
        allow writes.

        Backend-specific enforcement:

        * **SQLite** — no role-based read-only mechanism exists; the check is
          skipped.  Pass ``?mode=ro`` in the URI for OS-level enforcement.
        * **PostgreSQL** — the session is set to ``READ ONLY`` and we verify
          that a DDL statement is rejected.  ``connect_timeout`` and
          ``statement_timeout`` are applied so a misconfigured host never hangs
          the agent indefinitely.
        * **MySQL / MariaDB** — ``SET SESSION TRANSACTION READ ONLY`` is issued
          and DDL rejection is confirmed.  ``connect_timeout`` is applied.
        * **Other dialects** — fall back to the original CREATE TABLE probe
          inside an explicit (never-committed) transaction.

        refresh_mode:
          "always" — every query() call hits the live database, no caching
          "ttl"    — query results are cached in-memory for ttl_seconds
        """
        if refresh_mode not in ("always", "ttl"):
            raise ValueError(f"refresh_mode must be 'always' or 'ttl', got {refresh_mode!r}")

        dialect = _dialect_from_url(connection_string)
        engine_kwargs = _engine_kwargs_for_dialect(dialect)

        self._engine = create_engine(connection_string, pool_pre_ping=True, **engine_kwargs)
        self._is_live = True
        self._refresh_mode = refresh_mode
        self._live_table_name = table_name
        self.table_name = table_name
        self._query_cache = TTLCache(maxsize=200, ttl=ttl_seconds) if refresh_mode == "ttl" else None
        self._cache_lock = threading.Lock()

        self._verify_readonly_connection(dialect)

        # Build the profile once at connect time, same as static loaders —
        # metric_factory.py needs this regardless of live/static mode.
        sample_df = self._fetch_live(f"SELECT * FROM {table_name} LIMIT 500")
        self._build_profile_from_dataframe(sample_df, table_name)

    def _verify_readonly_connection(self, dialect: str = "") -> None:
        """Actively enforce that the connection cannot perform writes.

        Strategy per dialect:

        ``sqlite``
            Skipped — SQLite has no role-level read-only mechanism.  Users
            should append ``?mode=ro&uri=true`` to the SQLite URI if they need
            OS-level enforcement.

        ``postgresql`` / ``postgres``
            1. Issue ``SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY``
               so the session itself is read-only.
            2. Confirm the session obeys by attempting a DDL inside an
               *explicit* (autocommit-off) transaction and asserting it fails.

        ``mysql`` / ``mariadb``
            1. Issue ``SET SESSION TRANSACTION READ ONLY``.
            2. Same DDL-probe confirmation.

        All other dialects
            Original behaviour: attempt DDL inside an explicit transaction,
            expect a permission error from the DB server.

        In every non-SQLite case, a ``PermissionError`` is raised immediately
        with a clear, actionable message if the connection turns out to be
        writable.
        """
        if self._engine is None:
            return

        if dialect == "sqlite":
            # SQLite has no role-based read-only permissions — skip the check.
            # See connect_live() docstring for URI workaround.
            return

        if dialect in ("postgresql", "postgres"):
            self._verify_readonly_postgres()
        elif dialect in ("mysql", "mariadb"):
            self._verify_readonly_mysql()
        else:
            self._verify_readonly_generic()

    def _verify_readonly_postgres(self) -> None:
        """PostgreSQL-specific read-only enforcement.

        Steps:
        1. Set the session to READ ONLY.
        2. Probe with a DDL — if it succeeds, that means the server honours
           the session setting but the *role* still has CREATE privileges; we
           reject with a clear message.
        """
        test_table = f"_ro_check_{int(time.time())}"
        try:
            with self._engine.connect() as conn:
                # Disable autocommit so we control the transaction boundary.
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                # Force the session to read-only.  This alone is enough for
                # pg_dump style connections, but we also probe to be sure.
                conn.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"))

            # Now probe: open a proper transaction and attempt DDL.
            # The session READ ONLY setting should block it.
            with self._engine.begin() as conn:
                conn.execute(text(f"CREATE TABLE {test_table} (id INTEGER)"))
                # If we reach here the DB allowed DDL despite READ ONLY — reject.
                conn.execute(text(f"DROP TABLE IF EXISTS {test_table}"))

        except PermissionError:
            raise
        except Exception as exc:
            # Any error from the DDL probe is the expected, safe outcome.
            err_lower = str(exc).lower()
            # Distinguish "rejected because read-only" (good) from genuine
            # connection / timeout problems (re-raise so the caller sees them).
            _READONLY_SIGNALS = (
                "read-only transaction",
                "read only transaction",
                "cannot execute",
                "permission denied",
                "pg_e",         # PostgreSQL error prefix in some drivers
                "read_only",
                "not allowed",
            )
            if any(sig in err_lower for sig in _READONLY_SIGNALS):
                return  # ✓ connection correctly refused the write
            # Connection problem / unexpected error — surface it.
            raise ConnectionError(
                f"connect_live() could not verify Postgres read-only status: {exc}\n"
                "Ensure the host is reachable, the credentials are correct, "
                "and the role has SELECT privileges on the target table."
            ) from exc
        else:
            # The DDL succeeded and we raised nothing — connection is WRITABLE.
            raise PermissionError(
                "connect_live() refused: the Postgres connection allows DDL writes.\n"
                "Fix: create a dedicated read-only role and grant it SELECT only:\n"
                "  CREATE ROLE analytics_ro NOINHERIT;\n"
                "  GRANT CONNECT ON DATABASE yourdb TO analytics_ro;\n"
                "  GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_ro;\n"
                "  ALTER DEFAULT PRIVILEGES IN SCHEMA public\n"
                "    GRANT SELECT ON TABLES TO analytics_ro;\n"
                "Then pass the connection string for that role to connect_live()."
            )

    def _verify_readonly_mysql(self) -> None:
        """MySQL / MariaDB-specific read-only enforcement.

        Steps:
        1. Issue ``SET SESSION TRANSACTION READ ONLY`` — MySQL 5.6+ / MariaDB 10+.
        2. Probe with a DDL inside a transaction to confirm rejection.
        """
        test_table = f"_ro_check_{int(time.time())}"
        try:
            with self._engine.connect() as conn:
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                conn.execute(text("SET SESSION TRANSACTION READ ONLY"))

            with self._engine.begin() as conn:
                conn.execute(text(f"CREATE TABLE {test_table} (id INT)"))
                conn.execute(text(f"DROP TABLE IF EXISTS {test_table}"))

        except PermissionError:
            raise
        except Exception as exc:
            err_lower = str(exc).lower()
            _READONLY_SIGNALS = (
                "read-only",
                "read only",
                "cannot execute",
                "access denied",
                "1792",   # MySQL: ER_CANT_EXECUTE_IN_READ_ONLY_TRANSACTION
                "er_",
                "not allowed",
                "permission",
            )
            if any(sig in err_lower for sig in _READONLY_SIGNALS):
                return  # ✓ correctly refused the write
            raise ConnectionError(
                f"connect_live() could not verify MySQL read-only status: {exc}\n"
                "Ensure the host is reachable, credentials are correct, "
                "and the user has SELECT privileges on the target table."
            ) from exc
        else:
            raise PermissionError(
                "connect_live() refused: the MySQL connection allows DDL writes.\n"
                "Fix: create a dedicated read-only user:\n"
                "  CREATE USER 'analytics_ro'@'%' IDENTIFIED BY '<password>';\n"
                "  GRANT SELECT ON yourdb.* TO 'analytics_ro'@'%';\n"
                "  FLUSH PRIVILEGES;\n"
                "Then pass the connection string for that user to connect_live()."
            )

    def _verify_readonly_generic(self) -> None:
        """Generic read-only probe for other SQLAlchemy-supported dialects.

        Attempts DDL inside an explicit transaction (never committed).  If the
        DB server rejects it (permission error) the connection is considered
        read-only.  If DDL succeeds, we reject with a PermissionError.
        """
        test_table = f"_ro_check_{int(time.time())}"
        try:
            with self._engine.begin() as conn:
                conn.execute(text(f"CREATE TABLE {test_table} (id INTEGER)"))
                # If we get here without error, the connection is writable.
                # Attempt cleanup before raising.
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {test_table}"))
                except Exception:
                    pass

        except PermissionError:
            raise
        except Exception:
            # DB rejected the DDL — this is the expected, safe outcome.
            return
        else:
            raise PermissionError(
                "connect_live() refused: this connection string appears to have WRITE "
                "access. Pass a connection string for a READ-ONLY database role only."
            )

    def _fetch_live(self, sql: str, params: list | dict | None = None) -> pd.DataFrame:
        if self._engine is None:
            raise RuntimeError("connect_live() has not been called.")
        with self._engine.connect() as conn:
            if params:
                return pd.read_sql_query(text(sql), conn, params=params)
            return pd.read_sql_query(text(sql), conn)

    def _build_profile_from_dataframe(self, df: pd.DataFrame, table_name: str) -> None:
        """Build a TableProfile from a DataFrame (used by live mode)."""
        n_rows = len(df)
        columns = []
        for col in df.columns:
            s = df[col]
            dtype = str(s.dtype)
            is_num = pd.api.types.is_numeric_dtype(s)
            is_temp = pd.api.types.is_datetime64_any_dtype(s) or "date" in col.lower()
            n_unique = int(s.nunique(dropna=True))
            is_cat = (not is_num) and n_unique <= min(50, max(10, n_rows // 20))

            examples = s.dropna().head(3).tolist()
            examples = [
                str(x) if not isinstance(x, (int, float, str, bool)) else x
                for x in examples
            ]

            columns.append(
                ColumnProfile(
                    name=col,
                    dtype=dtype,
                    n_unique=n_unique,
                    n_null=int(s.isna().sum()),
                    examples=examples,
                    is_numeric=is_num,
                    is_temporal=is_temp,
                    is_categorical=is_cat,
                )
            )

        sample = df.head(5).to_dict(orient="records")
        for row in sample:
            for k, v in row.items():
                if not isinstance(v, (int, float, str, bool, type(None))):
                    row[k] = str(v)

        self.profile = TableProfile(
            name=table_name,
            n_rows=n_rows,
            n_cols=len(columns),
            columns=columns,
            sample_rows=sample,
        )

        self._allowed_filter_columns = [
            c.name
            for c in columns
            if c.is_categorical or c.is_temporal or (c.n_unique and c.n_unique <= 30)
        ]

        self._metrics_cache = None

    def is_live(self) -> bool:
        return self._is_live

    # ── Profiling ──────────────────────────────────────────────────────────

    def _build_profile(self, sample_size: int = 5) -> None:
        df = self.con.execute(f"SELECT * FROM {self.table_name} LIMIT 10000").fetchdf()
        n_rows = self.con.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0]

        columns = []
        for col in df.columns:
            s = df[col]
            dtype = str(s.dtype)
            is_num = pd.api.types.is_numeric_dtype(s)
            is_temp = pd.api.types.is_datetime64_any_dtype(s) or "date" in col.lower()
            n_unique = int(s.nunique(dropna=True))
            is_cat = (not is_num) and n_unique <= min(50, max(10, n_rows // 20))

            examples = s.dropna().head(3).tolist()
            examples = [
                str(x) if not isinstance(x, (int, float, str, bool)) else x
                for x in examples
            ]

            columns.append(
                ColumnProfile(
                    name=col,
                    dtype=dtype,
                    n_unique=n_unique,
                    n_null=int(s.isna().sum()),
                    examples=examples,
                    is_numeric=is_num,
                    is_temporal=is_temp,
                    is_categorical=is_cat,
                )
            )

        sample = df.head(sample_size).to_dict(orient="records")
        for row in sample:
            for k, v in row.items():
                if not isinstance(v, (int, float, str, bool, type(None))):
                    row[k] = str(v)

        self.profile = TableProfile(
            name=self.table_name,
            n_rows=n_rows,
            n_cols=len(columns),
            columns=columns,
            sample_rows=sample,
        )

        self._allowed_filter_columns = [
            c.name
            for c in columns
            if c.is_categorical or c.is_temporal or (c.n_unique and c.n_unique <= 30)
        ]

        self._metrics_cache = None

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def allowed_filter_columns(self) -> list[str]:
        return self._allowed_filter_columns

    @property
    def pii_masked_columns(self) -> set[str]:
        """Names of columns that were PII-masked during loading."""
        return self._pii_masked_columns

    @property
    def dataset_id(self) -> str:
        """Stable identity for this DataSource INSTANCE.

        Used to scope the response cache (see cache.py) per-session/tenant
        so two DataSource instances never share a cache entry — even if
        they happen to hold data with an identical schema (same column
        names/dtypes/row count but different values — e.g. two tenants
        both uploading an "order_id, revenue, region" CSV). Assigned once
        at construction and never changes, matching how api_widget.py
        already scopes one DataSource per session.
        """
        return self._instance_id

    def get_metrics(self) -> dict:
        """Return cached metrics, generating them on first access."""
        if self._metrics_cache is None:
            from metric_factory import generate_metrics
            self._metrics_cache = generate_metrics(self)
        return self._metrics_cache

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Only called by the safe execution layer -- never by the LLM.

        If this DataSource was created via connect_live(), routes through the
        live connection (with caching per refresh_mode). Otherwise, falls back
        to the original static DuckDB behavior. Signature is UNCHANGED.
        """
        if not self._is_live:
            if params:
                return self.con.execute(sql, params).fetchdf()
            return self.con.execute(sql).fetchdf()

        if self._refresh_mode == "always":
            return self._fetch_live(sql, params)

        # refresh_mode == "ttl"
        cache_key = (
            sql,
            tuple(params) if isinstance(params, list) else tuple(params or ()),
        )
        with self._cache_lock:
            if cache_key in self._query_cache:
                return self._query_cache[cache_key].copy()

        result = self._fetch_live(sql, params)

        with self._cache_lock:
            self._query_cache[cache_key] = result.copy()

        return result

    def get_schema_card(self) -> str:
        """Compact, LLM-friendly schema description."""
        if not self.profile:
            return "No data loaded."
        lines = [
            f"Table: {self.profile.name}",
            f"Rows: {self.profile.n_rows:,} | Columns: {self.profile.n_cols}",
            "",
            "Columns:",
        ]
        for c in self.profile.columns:
            flags = []
            if c.is_numeric:
                flags.append("numeric")
            if c.is_categorical:
                flags.append("categorical")
            if c.is_temporal:
                flags.append("temporal")
            flag_str = f" ({', '.join(flags)})" if flags else ""
            ex = f" e.g. {c.examples}" if c.examples else ""
            lines.append(f"  - {c.name}: {c.dtype}{flag_str}{ex}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level helpers for dialect detection and engine configuration
# ---------------------------------------------------------------------------

def _dialect_from_url(connection_string: str) -> str:
    """Return a normalised dialect name from a SQLAlchemy URL string.

    Examples:
        ``postgresql+psycopg2://...`` → ``"postgresql"``
        ``mysql+pymysql://...``       → ``"mysql"``
        ``sqlite:///...``             → ``"sqlite"``
    """
    url_lower = connection_string.lower().split("://")[0]
    # Strip driver suffix (e.g. "+psycopg2", "+pymysql")
    base = url_lower.split("+")[0].strip()
    # Normalise aliases
    if base in ("postgres",):
        return "postgresql"
    if base in ("mariadb",):
        return "mysql"
    return base


def _engine_kwargs_for_dialect(dialect: str) -> dict:
    """Return SQLAlchemy ``create_engine`` keyword arguments suitable for the dialect.

    Applies conservative connection and statement timeouts so a misconfigured
    or unreachable host never hangs the agent indefinitely.
    """
    if dialect in ("postgresql", "postgres"):
        return {
            "connect_args": {
                "connect_timeout": _CONNECT_TIMEOUT_POSTGRES,
                # statement_timeout is a PostgreSQL GUC (milliseconds).
                "options": f"-c statement_timeout={_STATEMENT_TIMEOUT_POSTGRES}",
            },
        }
    if dialect in ("mysql", "mariadb"):
        return {
            "connect_args": {
                "connect_timeout": _CONNECT_TIMEOUT_MYSQL,
            },
        }
    return {}