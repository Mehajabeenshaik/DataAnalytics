"""
dataset_registry.py — holds multiple named DataSource instances per session,
plus raw named tables for governed multi-table joins.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from data_source import DataSource


class DatasetRegistry:
    """Simple name → DataSource map with a default dataset.

    Also holds raw named tables (register_table) used by governed joins.
    get_joined_view() only ever merges tables via an APPROVED join policy
    dict resolved from CatalogService.get_approved_joins() — it never
    accepts arbitrary table/key names from the planner.
    """

    def __init__(self):
        self._datasets: Dict[str, DataSource] = {}
        self._default_name: Optional[str] = None
        self._tables: Dict[str, pd.DataFrame] = {}

    def add(self, name: str, ds: DataSource, make_default: bool = False) -> None:
        name = (name or "default").strip().lower()
        self._datasets[name] = ds
        if make_default or self._default_name is None:
            self._default_name = name

    def get(self, name: Optional[str] = None) -> DataSource:
        """Return the requested dataset or the default one."""
        if not self._datasets:
            raise ValueError("No datasets loaded")

        key = (name or self._default_name or "").strip().lower()
        if key not in self._datasets:
            # graceful fallback to default
            key = self._default_name  # type: ignore
        return self._datasets[key]

    def list_names(self) -> List[str]:
        return sorted(self._datasets.keys())

    def has(self, name: str) -> bool:
        return name.strip().lower() in self._datasets

    @property
    def default_name(self) -> Optional[str]:
        return self._default_name

    def __len__(self) -> int:
        return len(self._datasets)

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    # ── Governed multi-table joins ────────────────────────────────────────

    def register_table(self, name: str, df: pd.DataFrame) -> None:
        """Register a named raw table for use in governed joins."""
        self._tables[name] = df

    def get_table(self, name: str) -> pd.DataFrame:
        """Return a registered table by name, or raise ValueError."""
        if name not in self._tables:
            raise ValueError(f"Unknown table: {name}")
        return self._tables[name]

    def get_joined_view(self, join_policy: dict) -> pd.DataFrame:
        """Merge two registered tables per an APPROVED join policy.

        join_policy is a resolved dict from CatalogService.get_approved_joins()
        (left_table/right_table/left_key/right_key/join_type). It never
        accepts raw table/key names from the planner directly — the planner
        only ever references a join_policy_name, resolved server-side.
        """
        left = self.get_table(join_policy["left_table"])
        right = self.get_table(join_policy["right_table"])
        return left.merge(
            right,
            left_on=join_policy["left_key"],
            right_on=join_policy["right_key"],
            how=join_policy["join_type"],
            suffixes=("", "_joined"),
        )
