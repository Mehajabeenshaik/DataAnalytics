from typing import List, Optional

from .models import MetricDefinition, MetricProposal
from .store import get, set, list_all

class CatalogService:
    """Service layer for managing tenant-scoped metric catalog."""

    def list_approved(self, tenant_id: str = "default") -> List[MetricDefinition]:
        """Return all metrics for tenant_id whose status is approved."""
        return [m for m in list_all(tenant_id) if m.status == "approved"]

    def get(self, name: str, tenant_id: str = "default") -> Optional[MetricDefinition]:
        """Retrieve a metric by name and tenant_id, regardless of status."""
        return get(name, tenant_id)

    def propose(self, proposal: MetricProposal) -> MetricProposal:
        """Add a new metric proposal for a tenant."""
        metric = MetricDefinition(
            name=proposal.name,
            tenant_id=proposal.tenant_id,
            description=proposal.description,
            synonyms=proposal.synonyms,
            sql_template=proposal.sql_template,
            allowed_filters=proposal.allowed_filters,
            version=proposal.version,
            status="proposed",
        )
        set(metric)
        return proposal

    def approve(self, name: str, tenant_id: str = "default") -> bool:
        """Mark an existing metric as approved for tenant_id. Returns True if successful."""
        metric = self.get(name, tenant_id)
        if metric is None:
            return False
        metric.status = "approved"
        set(metric)
        return True

    def reject(self, name: str, tenant_id: str = "default") -> bool:
        """Mark an existing metric as rejected for tenant_id. Returns True if successful."""
        metric = self.get(name, tenant_id)
        if metric is None:
            return False
        metric.status = "rejected"
        set(metric)
        return True
