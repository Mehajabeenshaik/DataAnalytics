"""
Phase 1 DataSource abstraction.
Supports local files (CSV/Parquet) and DuckDB.
All analysis goes through a single registered source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel, Field


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

    # ── Loading methods ────────────────────────────────────────────────────

    def load_file(self, path: str | Path, table_name: str = "data") -> None:
        path = Path(path)
        self.table_name = table_name

        if path.suffix.lower() in {".csv", ".tsv"}:
            self.con.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS "
                f"SELECT * FROM read_csv_auto('{path.as_posix()}', HEADER=TRUE, SAMPLE_SIZE=10000)"
            )
        elif path.suffix.lower() in {".parquet", ".pq"}:
            self.con.execute(
                f"CREATE OR REPLACE TABLE {table_name} AS "
                f"SELECT * FROM read_parquet('{path.as_posix()}')"
            )
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")

        self._build_profile()

    def load_dataframe(self, df: pd.DataFrame, table_name: str = "data") -> None:
        self.table_name = table_name
        # Convert pandas 'str' dtype to 'object' for DuckDB compatibility
        # (older DuckDB versions don't recognize the newer pandas StringDtype)
        df = df.copy()
        for col in df.columns:
            if df[col].dtype == "string" or str(df[col].dtype).startswith("str"):
                df[col] = df[col].astype("object")
        self.con.register("tmp_df", df)
        self.con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM tmp_df")
        self.con.unregister("tmp_df")
        self._build_profile()

    def load_sqlite(self, db_path: str, query: str = "SELECT * FROM orders_enriched") -> None:
        """Bridge to an existing SQLite database (e.g. ecommerce.db).

        Tries DuckDB's native SQLite ATTACH first; falls back to pandas
        if the sqlite extension is unavailable.
        """
        import re

        # Normalise Windows back-slashes — DuckDB expects POSIX paths.
        norm_path = db_path.replace("\\", "/")

        try:
            self.con.execute(f"ATTACH '{norm_path}' AS src (TYPE SQLITE)")

            # Build a schema-qualified query.
            # If the caller passed a bare table name (no spaces / SELECT),
            # wrap it.  Otherwise treat it as a full SELECT and rewrite
            # bare table references to ``src.<table>`` via regex.
            stripped = query.strip()
            if not re.search(r"\s", stripped):
                # Bare table name, e.g. "orders_enriched"
                safe_query = f"SELECT * FROM src.{stripped}"
            elif re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
                # Full SELECT — rewrite FROM/JOIN <table> → src.<table>
                safe_query = re.sub(
                    r"(\bFROM\s+|\bJOIN\s+)([A-Za-z_][A-Za-z0-9_]*)",
                    r"\1src.\2",
                    stripped,
                )
            else:
                # Fallback: assume bare table name
                safe_query = f"SELECT * FROM src.{stripped}"

            self.con.execute(f"CREATE OR REPLACE TABLE data AS {safe_query}")
            self.table_name = "data"
            self._build_profile()
        except Exception:
            # Fallback: use pandas to read from SQLite, then load via DataFrame
            import sqlite3

            conn = sqlite3.connect(db_path)
            df = pd.read_sql_query(query, conn)
            conn.close()
            self.load_dataframe(df, "data")

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
            # make JSON-serializable
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
        # serialize sample safely
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

        # Safe filter columns = categorical + temporal + low-cardinality
        self._allowed_filter_columns = [
            c.name
            for c in columns
            if c.is_categorical or c.is_temporal or (c.n_unique and c.n_unique <= 30)
        ]

        # Invalidate metrics cache when data changes
        self._metrics_cache = None

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def allowed_filter_columns(self) -> list[str]:
        return self._allowed_filter_columns

    def get_metrics(self) -> dict:
        """Return cached metrics, generating them on first access."""
        if self._metrics_cache is None:
            from metric_factory import generate_metrics

            self._metrics_cache = generate_metrics(self)
        return self._metrics_cache

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """Only called by the safe execution layer -- never by the LLM."""
        if params:
            return self.con.execute(sql, params).fetchdf()
        return self.con.execute(sql).fetchdf()

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