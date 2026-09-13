from __future__ import annotations

import secrets
from threading import Lock
from typing import Any, Dict, Optional
from pydantic import BaseModel

CONSEQUENTIAL_ACTIONS = {
    "export_external",
    "write_back",
    "send_report",
    "propose_metric",
}


class PendingConfirmation(BaseModel):
    token: str
    tenant_id: str
    question: str
    action_type: str
    plan_details: Dict[str, Any]
    status: str = "pending"  # pending | approved | rejected


class ConfirmationManager:
    """Manager for consequential action confirmations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: Dict[str, PendingConfirmation] = {}

    def is_consequential(self, action_type: str) -> bool:
        return action_type in CONSEQUENTIAL_ACTIONS

    def create_request(
        self, tenant_id: str, question: str, action_type: str, plan_details: Dict[str, Any]
    ) -> PendingConfirmation:
        token = f"confirm_{secrets.token_hex(16)}"
        item = PendingConfirmation(
            token=token,
            tenant_id=tenant_id,
            question=question,
            action_type=action_type,
            plan_details=plan_details,
        )
        with self._lock:
            self._pending[token] = item
        return item

    def get_pending(self, token: str) -> Optional[PendingConfirmation]:
        with self._lock:
            return self._pending.get(token)

    def resolve(self, token: str, approve: bool) -> Optional[PendingConfirmation]:
        with self._lock:
            item = self._pending.get(token)
            if not item:
                return None
            item.status = "approved" if approve else "rejected"
            del self._pending[token]
            return item


_global_manager = ConfirmationManager()


def get_confirmation_manager() -> ConfirmationManager:
    return _global_manager
