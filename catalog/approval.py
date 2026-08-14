"""
Approval logic + audit logging for the metric catalog.

Wraps the low-level store operations with human-identity tracking and writes
an audit trail via audit_logger.log_action() so every propose/approve/reject
is attributable to a person and timestamped.
"""

from __future__ import annotations

from datetime import datetime

from .models import MetricDefinition, MetricProposal
from .store import CatalogStore


class ApprovalService:
    """Human-in-the-loop approval workflow.

    Responsibilities:
      - propose(): persist a pending proposal + audit the action
      - approve(): move a pending proposal into the approved catalog,
                   stamp approved_by/approved_at, bump the version history,
                   and audit the action
      - reject():  mark a proposal rejected (never enters the catalog) + audit

    All column/agg validation happens upstream in the deterministic layer
    (agent_phase2.propose_metric) — this service only governs the lifecycle.
    """

    def __init__(self, store: CatalogStore | None = None):
        self.store = store or CatalogStore()

    def _audit(self, username: str, action_type: str, details: dict) -> None:
        """Best-effort audit write. Never raises — the catalog workflow must
        not fail because the audit DB is unavailable."""
        try:
            from audit_logger import log_action

            log_action(
                username=username,
                role="analyst",
                action_type=action_type,
                details=details,
            )
        except Exception:
            # Audit is a side-channel; a failure here must not block approval.
            pass

    def propose(self, proposal: MetricProposal, proposed_by: str = "agent") -> str:
        """Persist a new pending proposal and return its id."""
        proposal.proposed_by = proposed_by
        proposal.status = "pending"
        self.store.save_proposal(proposal)
        self._audit(
            proposed_by,
            "METRIC_PROPOSE",
            {
                "proposal_id": proposal.proposal_id,
                "metric_name": proposal.metric.name,
                "column": proposal.metric.column,
                "agg": proposal.metric.agg,
                "question": proposal.question,
            },
        )
        return proposal.proposal_id

    def approve(
        self,
        proposal_id: str,
        approved_by: str,
        note: str | None = None,
    ) -> MetricDefinition:
        """Approve a pending proposal, adding it to the approved catalog.

        Raises ValueError if the proposal doesn't exist or was already reviewed.
        """
        prop = self.store.load_proposal(proposal_id)
        if not prop or prop.status != "pending":
            raise ValueError("Invalid or already-reviewed proposal")

        metrics = self.store.load_approved()
        metric = prop.metric
        metric.status = "approved"
        metric.approved_by = approved_by
        metric.approved_at = datetime.utcnow()
        metric.proposal_id = proposal_id
        metric.source = "proposed"
        metrics[metric.name] = metric

        self.store.save_approved(metrics, note=f"approved {metric.name}")
        prop.status = "approved"
        prop.review_note = note
        self.store.save_proposal(prop)

        self._audit(
            approved_by,
            "METRIC_APPROVE",
            {
                "proposal_id": proposal_id,
                "metric_name": metric.name,
                "column": metric.column,
                "agg": metric.agg,
                "note": note,
            },
        )
        return metric

    def reject(
        self,
        proposal_id: str,
        rejected_by: str,
        reason: str,
    ) -> None:
        """Reject a pending proposal. It never enters the approved catalog."""
        prop = self.store.load_proposal(proposal_id)
        if not prop or prop.status != "pending":
            raise ValueError("Invalid or already-reviewed proposal")

        prop.status = "rejected"
        prop.review_note = reason
        self.store.save_proposal(prop)

        self._audit(
            rejected_by,
            "METRIC_REJECT",
            {
                "proposal_id": proposal_id,
                "metric_name": prop.metric.name,
                "reason": reason,
            },
        )