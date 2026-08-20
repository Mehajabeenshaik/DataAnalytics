"""
Versioned Metric Catalog — governed, durable, auditable semantic layer.

Phase 1 of the DataAnalytics governed-agent roadmap. Turns the previously
in-memory, auto-generated metric dict into a durable, versioned catalog with
a human-in-the-loop proposal/approval workflow.

Public API (see catalog/service.py):
    CatalogService
        .seed_from_datasource(ds)   # first-load seeding of auto metrics
        .get_approved_metrics()     # LLM-visible approved metrics only
        .propose(proposal)          # create a pending proposal
        .approve(proposal_id, by)   # approve -> enters approved catalog + version bump
        .reject(proposal_id, by)    # reject -> never enters catalog
        .get_catalog_for_llm()      # name/synonyms/description only
"""

from .models import MetricDefinition, MetricProposal, CatalogVersion
from .store import CatalogStore
from .service import CatalogService

__all__ = [
    "MetricDefinition",
    "MetricProposal",
    "CatalogVersion",
    "CatalogStore",
    "CatalogService",
]