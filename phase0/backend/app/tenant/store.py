from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from .models import Tenant, TenantQuota
from ..config import TENANT_STORE_PATH


class TenantStore:
    """Thread-safe, file-backed JSON store for Tenant definitions."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        self.file_path = Path(file_path or TENANT_STORE_PATH)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cache: Dict[str, Tenant] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.file_path.exists():
                self._cache = {}
                return
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cache = {tid: Tenant(**tdata) for tid, tdata in data.items()}
            except Exception:
                self._cache = {}

    def _save(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            data = {tid: t.model_dump() for tid, t in self._cache.items()}
            json.dump(data, f, indent=2, ensure_ascii=False)

    def create(self, tenant: Tenant) -> Tenant:
        with self._lock:
            self._cache[tenant.id] = tenant
            self._save()
            return tenant

    def get(self, tenant_id: str) -> Optional[Tenant]:
        with self._lock:
            return self._cache.get(tenant_id)

    def list_all(self) -> List[Tenant]:
        with self._lock:
            return list(self._cache.values())

    def get_by_api_key(self, api_key: str) -> Optional[Tenant]:
        with self._lock:
            for tenant in self._cache.values():
                if api_key in tenant.api_keys:
                    return tenant
            return None
