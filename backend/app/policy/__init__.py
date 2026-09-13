"""Governed policy package (Phase 4).

Exports the policy gates consumed by the production agent orchestrator:
  - PolicyCritic / PolicyDecision (allowlist, non-evasion, confirmation)
  - ConfirmationManager (consequential-action approval)
  - check_grounding / attach_lineage (honesty)
  - sanitise_request / sanitise_data_text (injection resistance)
"""

from .critic import PolicyDecision, PolicyCritic, get_policy_critic
from .confirmation import (
    ConfirmationManager,
    get_confirmation_manager,
    CONSEQUENTIAL_ACTIONS,
    PendingConfirmation,
)
from .grounding import check_grounding, attach_lineage
from .injection import sanitise_request, sanitise_data_text, sanitize_data_content

__all__ = [
    "PolicyDecision",
    "PolicyCritic",
    "get_policy_critic",
    "ConfirmationManager",
    "get_confirmation_manager",
    "CONSEQUENTIAL_ACTIONS",
    "PendingConfirmation",
    "check_grounding",
    "attach_lineage",
    "sanitise_request",
    "sanitise_data_text",
    "sanitize_data_content",
]