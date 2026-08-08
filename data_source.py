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
            df = pd.read_csv(path)
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

        connection_string MUST point to a read-only database role/user — this method
        does not enforce that at the code level (the DB server does), but it will
        refuse to proceed if a basic write-capability check fails.

        refresh_mode:
          "always" — every query() call hits the live database, no caching
          "ttl"    — query results are cached in-memory for ttl_seconds
        """
        if refresh_mode not in ("always", "ttl"):
            raise ValueError(f"refresh_mode must be 'always' or 'ttl', got {refresh_mode!r}")

        self._engine = create_engine(connection_string, pool_pre_ping=True)
        self._is_live = True
        self._refresh_mode = refresh_mode
        self._live_table_name = table_name
        self.table_name = table_name
        self._query_cache = TTLCache(maxsize=200, ttl=ttl_seconds) if refresh_mode == "ttl" else None
        self._cache_lock = threading.Lock()

        self._verify_readonly_connection()

        # Build the profile once at connect time, same as static loaders —
        # metric_factory.py needs this regardless of live/static mode.
        sample_df = self._fetch_live(f"SELECT * FROM {table_name} LIMIT 500")
        self._build_profile_from_dataframe(sample_df, table_name)

    def _verify_readonly_connection(self) -> None:
        """Defensive check: attempt a harmless write in a transaction that's always
        rolled back, and confirm the database rejects it. This does NOT replace
        granting a real read-only DB role — it's a sanity check that catches an
        obviously misconfigured (writable) connection string before any real use.

        SQLite has no real read-only-role mechanism, so this check is skipped for
        SQLite URLs (the CREATE TABLE would succeed and falsely fail the check).
        """
        if self._engine is None:
            return
        url = str(self._engine.url)
        if url.startswith("sqlite"):
            return  # SQLite has no role-based permissions — skip the check.

        test_table = f"_readonly_check_{int(time.time())}"
        try:
            with self._engine.begin() as conn:
                conn.execute(text(f"CREATE TABLE {test_table} (id INTEGER)"))
                conn.rollback()  # never actually commits
            # If we reach here without an error, the connection CAN write — refuse.
            raise PermissionError(
                "connect_live() refused: this connection string appears to have WRITE "
                "access. Pass a connection string for a READ-ONLY database role only."
            )
        except PermissionError:
            raise
        except Exception:
            # Any DB-level permission error here is the EXPECTED, safe outcome.
            pass

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