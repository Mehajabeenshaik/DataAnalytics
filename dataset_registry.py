"""
dataset_registry.py — holds multiple named DataSource instances per session.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from data_source import DataSource


class DatasetRegistry:
    """Simple name → DataSource map with a default dataset."""

    def __init__(self):
        self._datasets: Dict[str, DataSource] = {}
        self._default_name: Optional[str] = None

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