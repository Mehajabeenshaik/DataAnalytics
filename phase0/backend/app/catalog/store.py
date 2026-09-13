from typing import Dict, List, Tuple
from .models import MetricDefinition

# In‑memory store for the catalog. Keys are (tenant_id, metric_name).
_store: Dict[Tuple[str, str], MetricDefinition] = {}

def get(name: str, tenant_id: str = "default") -> MetricDefinition | None:
    """Retrieve a metric definition by name and tenant_id, or ``None`` if not present."""
    return _store.get((tenant_id, name))

def set(metric: MetricDefinition) -> None:
    """Insert or replace a metric definition in the store."""
    _store[(metric.tenant_id, metric.name)] = metric

def list_all(tenant_id: str = "default") -> List[MetricDefinition]:
    """Return a list of stored metric definitions for a specific tenant_id."""
    return [m for (tid, _), m in _store.items() if tid == tenant_id]
