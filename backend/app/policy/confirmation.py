"""Consequential-action confirmation (Phase 4 policy).

Certain plan types are consequential (they write back, export externally,
send a report, or propose a metric). Before ANY side effect executes, the
agent must obtain explicit user confirmation. This module provides an
in-memory pending store with a TTL so an approval can only be granted while
the request is still fresh.
"""

from __future__ import annotations

import secrets
import time
from threading import Lock
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

# Plan types that must not execute until explicitly approved.
CONSEQUENTIAL_ACTIONS = {
    "export_external",
    "write_back",
    "send_report",
    "propose_metric",
}

# Default lifetime of a pending confirmation token (seconds).
DEFAULT_CONFIRMATION_TTL_SECONDS = 10 * 60


class PendingConfirmation(BaseModel):
    token: str
    tenant_id: str
    question: str
    action_type: str
    plan_details: Dict[str, Any]
    status: str = "pending"  # pending | approved | rejected
    created_at: float = Field(default_factory=time.time)
    ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds


class ConfirmationManager:
    """Thread-safe in-memory store for outstanding confirmation requests."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: Dict[str, PendingConfirmation] = {}

    def is_consequential(self, action_type: str) -> bool:
        return action_type in CONSEQUENTIAL_ACTIONS

    def create_request(
        self,
        tenant_id: str,
        question: str,
        action_type: str,
        plan_details: Dict[str, Any],
        ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS,
    ) -> PendingConfirmation:
        token = f"confirm_{secrets.token_hex(16)}"
        item = PendingConfirmation(
            token=token,
            tenant_id=tenant_id,
            question=question,
            action_type=action_type,
            plan_details=plan_details,
            ttl_seconds=ttl_seconds,
        )
        with self._lock:
            self._purge_expired()
            self._pending[token] = item
        return item

    def get_pending(self, token: str) -> Optional[PendingConfirmation]:
        with self._lock:
            item = self._pending.get(token)
            if item is None or item.expired:
                return None
            return item

    def resolve(self, token: str, approve: bool) -> Optional[PendingConfirmation]:
        """Resolve a pending token. Returns the item, or None if unknown/expired."""
        with self._lock:
            item = self._pending.get(token)
            if item is None or item.expired:
                return None
            item.status = "approved" if approve else "rejected"
            del self._pending[token]
            return item

    def _purge_expired(self) -> None:
        expired = [t for t, it in self._pending.items() if it.expired]
        for t in expired:
            del self._pending[t]


_global_manager = ConfirmationManager()


def get_confirmation_manager() -> ConfirmationManager:
    return _global_manager