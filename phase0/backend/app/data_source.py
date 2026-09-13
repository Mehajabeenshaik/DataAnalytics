"""
DataSource — Phase 0 & Phase 3.

Loads CSV data into an in‑memory DuckDB table and produces a schema profile.
CRITICAL SYSTEMS RULE: this connection is never given raw SQL that originated
from an LLM. All future query construction must go through approved metrics
or fixed statistical tools.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

from .config import DEFAULT_MAX_FILE_SIZE_MB, DEFAULT_MAX_ROWS_PER_QUERY

logger = logging.getLogger("daana.data")


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    n_unique: int | None = None
    n_null: int = 0
    examples: list[Any] = Field(default_factory=list)
    is_numeric: bool = False


class TableProfile(BaseModel):
    name: str
    n_rows: int
    n_cols: int
    columns: list[ColumnProfile]
    sample_rows: list[dict] = Field(default_factory=list)


class DataSource:
    """Single registered analytical source for the agent, scoped by tenant."""

    def __init__(self, name: str = "main", tenant_id: str = "default"):
        self.name = name
        self.tenant_id = tenant_id
        self.con = duckdb.connect(database=":memory:")
        self.table_name = "data"
        self.profile: TableProfile | None = None

    @property
    def duckdb_conn(self) -> duckdb.DuckDBPyConnection:
        return self.con

    def load_csv(self, path: str | Path, max_rows: int | None = None) -> TableProfile:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")

        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > DEFAULT_MAX_FILE_SIZE_MB:
            raise ValueError(
                f"File {path.name} is {size_mb:.1f} MB; limit is {DEFAULT_MAX_FILE_SIZE_MB} MB"
            )

        df = pd.read_csv(path)
        if df.empty:
            raise ValueError("CSV contains no rows")

        limit = max_rows or DEFAULT_MAX_ROWS_PER_QUERY
        if len(df) > limit:
            logger.warning("Truncating %s from %d to %d rows", path.name, len(df), limit)
            df = df.head(limit)

        # Phase 2: mask any PII in the dataframe before registration
        try:
            from .pii_masker import mask_dataframe
            df = mask_dataframe(df)
        except Exception as e:
            logger.error("Failed to mask PII: %s", e)
        # Register with DuckDB. Future phases will only run controlled queries.
        self.con.register(self.table_name, df)
        self.con.register("sales", df)
        self.profile = self._build_profile(df)
        logger.info(
            "Loaded %s for tenant %s → %d rows, %d cols (invariant: no LLM SQL will run here)",
            path.name,
            self.tenant_id,
            self.profile.n_rows,
            self.profile.n_cols,
        )
        return self.profile

    def _build_profile(self, df: pd.DataFrame) -> TableProfile:
        columns: list[ColumnProfile] = []
        for col in df.columns:
            series = df[col]
            is_numeric = pd.api.types.is_numeric_dtype(series)
            examples = (
                series.dropna().head(3).tolist() if len(series.dropna()) > 0 else []
            )
            columns.append(
                ColumnProfile(
                    name=str(col),
                    dtype=str(series.dtype),
                    n_unique=int(series.nunique(dropna=True)),
                    n_null=int(series.isna().sum()),
                    examples=examples,
                    is_numeric=is_numeric,
                )
            )
        sample = df.head(3).to_dict(orient="records")
        return TableProfile(
            name=self.table_name,
            n_rows=len(df),
            n_cols=len(df.columns),
            columns=columns,
            sample_rows=sample,
        )

    def schema_card(self) -> str:
        """Human‑ and LLM‑readable schema summary."""
        if self.profile is None:
            return "No data loaded."
        lines = [
            f"Table: {self.profile.name}",
            f"Tenant: {self.tenant_id}",
            f"Rows: {self.profile.n_rows}  Columns: {self.profile.n_cols}",
            "Columns:",
        ]
        for c in self.profile.columns:
            ex = ", ".join(repr(x) for x in c.examples[:2])
            lines.append(f"  - {c.name} ({c.dtype})  nulls={c.n_null}  examples=[{ex}]")
        return "\n".join(lines)

    @property
    def column_names(self) -> List[str]:
        """Return list of column names from the loaded profile."""
        if self.profile is None:
            raise RuntimeError("DataSource has no loaded data.")
        return [c.name for c in self.profile.columns]

    def load_dataframe(self) -> pd.DataFrame:
        """Retrieve the full DataFrame from DuckDB."""
        try:
            df = self.con.execute(f"SELECT * FROM {self.table_name}").fetchdf()
            return df
        except Exception as e:
            raise RuntimeError(f"Failed to load dataframe from DuckDB: {e}")
