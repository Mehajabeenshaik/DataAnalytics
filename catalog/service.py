"""
High-level public API for the versioned metric catalog.

This is the single entrypoint the rest of the system (agent_phase2, demo,
widget) should use. It guarantees:
  - Only status == "approved" metrics are ever exposed to the LLM planner.
  - Auto-generated metrics are seeded once and never overwrite human edits.
  - Proposals are durable and require human approval before entering the
    approved catalog.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from data_source import DataSource
from metric_factory import generate_metrics

from .approval import ApprovalService
from .models import MetricDefinition, MetricProposal, JoinPolicy, JoinProposal
from .store import CatalogStore


class CatalogService:
    """Facade over CatalogStore + ApprovalService.

    Backward compatible with the existing agent contract: get_approved_metrics()
    returns the same {name: {synonyms, description, column, agg, groupby,
    base_filters}} shape that DataSource.get_metrics() used to return, so
    existing agent code keeps working unchanged.

    Tenant isolation: each CatalogService is scoped to a single tenant_id.
    The store root is data/catalog/<tenant_id>/ so approved metrics and
    proposals NEVER cross tenants.
    """

    def __init__(
        self,
        store: CatalogStore | None = None,
        tenant_id: str = "default",
    ):
        if store is None:
            store = CatalogStore(root=Path("data/catalog") / tenant_id)
        self.store = store
        self.tenant_id = tenant_id
        self.approval = ApprovalService(self.store, tenant_id=tenant_id)

    # ── LLM-visible approved metrics ──────────────────────────────────────

    def get_approved_metrics(self) -> dict[str, dict]:
        """Return approved metrics in the legacy agent-compatible shape.

        Only metrics with status == "approved" are included — drafts, pending
        proposals, rejected, and deprecated metrics are never exposed.
        """
        approved = self.store.load_approved()
        return {
            name: {
                "synonyms": m.synonyms,
                "description": m.description,
                "column": m.column,
                "agg": m.agg,
                "groupby": m.groupby,
                "base_filters": m.base_filters,
            }
            for name, m in approved.items()
            if m.status == "approved"
        }

    def get_catalog_for_llm(self) -> list[dict]:
        """Return the minimal name/synonyms/description catalog for the LLM.

        Mirrors metric_factory.get_metric_catalog_for_llm() so the planner
        prompt stays identical in shape — but sourced from the governed,
        approved catalog only.
        """
        return [
            {
                "name": name,
                "synonyms": m["synonyms"],
                "description": m["description"],
            }
            for name, m in self.get_approved_metrics().items()
        ]

    # ── Seeding ───────────────────────────────────────────────────────────

    def seed_from_datasource(
        self,
        ds: DataSource,
        created_by: str = "system",
    ) -> int:
        """On first load, turn auto-generated metrics into approved catalog
        entries (source="auto"). Never overwrites an existing catalog.

        Returns the number of metrics seeded (0 if the catalog already had
        content).
        """
        existing = self.store.load_approved()
        if existing:
            return 0  # never overwrite human-approved / previously seeded metrics

        auto = generate_metrics(ds)
        metrics: dict[str, MetricDefinition] = {}
        for name, m in auto.items():
            metrics[name] = MetricDefinition(
                name=name,
                synonyms=m.get("synonyms", []),
                description=m["description"],
                column=m["column"],
                agg=m["agg"],
                groupby=m.get("groupby"),
                base_filters=m.get("base_filters", {}),
                status="approved",
                source="auto",
                created_by=created_by,
                risk="low",
            )
        self.store.save_approved(metrics, note="auto-seed from datasource")
        return len(metrics)

    # ── Proposal workflow ─────────────────────────────────────────────────

    def propose(
        self,
        proposal: MetricProposal,
        proposed_by: str = "agent",
    ) -> str:
        """Create a pending proposal. Returns the proposal_id."""
        return self.approval.propose(proposal, proposed_by=proposed_by)

    def approve(
        self,
        proposal_id: str,
        approved_by: str,
        note: str | None = None,
    ) -> MetricDefinition:
        """Approve a pending proposal, adding it to the approved catalog."""
        return self.approval.approve(proposal_id, approved_by, note=note)

    def reject(
        self,
        proposal_id: str,
        rejected_by: str,
        reason: str,
    ) -> None:
        """Reject a pending proposal. It never enters the approved catalog."""
        self.approval.reject(proposal_id, rejected_by, reason)

    # ── Introspection helpers ─────────────────────────────────────────────

    def list_pending(self) -> list[MetricProposal]:
        """Return all proposals awaiting human review."""
        return self.store.list_pending()

    def list_proposals(self) -> list[MetricProposal]:
        """Return all proposals (any status)."""
        return self.store.list_proposals()

    def list_versions(self) -> list[dict]:
        """Return catalog version-history metadata, newest first."""
        return self.store.list_versions()

    def get_metric(self, name: str) -> MetricDefinition | None:
        """Return a single approved MetricDefinition by name, or None."""
        return self.store.load_approved().get(name)

    # ── Join policies ─────────────────────────────────────────────────────

    def get_approved_joins(self) -> dict[str, dict]:
        """Return approved join policies in a planner-safe shape.

        Only policies with status == "approved" are included. The planner
        may reference a join_policy_name; the actual table/key details are
        resolved server-side from this catalog — never from the LLM.
        """
        approved = self.store.load_approved_joins()
        return {
            name: {
                "left_table": j.left_table,
                "right_table": j.right_table,
                "left_key": j.left_key,
                "right_key": j.right_key,
                "join_type": j.join_type,
                "description": j.description,
            }
            for name, j in approved.items()
            if j.status == "approved"
        }

    def propose_join(self, proposal: JoinProposal) -> str:
        """Create a pending join proposal. Returns the proposal_id."""
        proposal.status = "pending"
        self.store.save_join_proposal(proposal)
        return proposal.proposal_id

    def approve_join(self, proposal_id: str, approved_by: str) -> JoinPolicy:
        """Approve a pending join proposal, adding it to the approved catalog."""
        prop = self.store.load_join_proposal(proposal_id)
        if not prop or prop.status != "pending":
            raise ValueError("Invalid or already reviewed join proposal")
        joins = self.store.load_approved_joins()
        j = prop.join
        j.status = "approved"
        j.approved_by = approved_by
        j.approved_at = datetime.utcnow()
        joins[j.name] = j
        self.store.save_approved_joins(joins)
        prop.status = "approved"
        self.store.save_join_proposal(prop)
        return j

    def reject_join(self, proposal_id: str, rejected_by: str, reason: str) -> None:
        """Reject a pending join proposal. It never enters the approved catalog."""
        prop = self.store.load_join_proposal(proposal_id)
        if not prop or prop.status != "pending":
            raise ValueError("Invalid or already reviewed join proposal")
        prop.status = "rejected"
        prop.review_note = reason
        self.store.save_join_proposal(prop)

    def list_pending_joins(self) -> list[JoinProposal]:
        """Return all join proposals awaiting human review."""
        return self.store.list_pending_joins()
