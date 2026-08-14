"""
Pydantic models for the versioned metric catalog.

These are the durable, governed artifacts that replace the previous
in-memory metric dicts. Every metric that reaches the LLM planner must be
an approved MetricDefinition persisted in the catalog store.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MetricDefinition(BaseModel):
    """A single governed metric.

    Only instances with status == "approved" are ever exposed to the LLM
    planner. Everything else (draft/pending/rejected/deprecated) is hidden
    from the agent and exists purely for the human approval workflow.
    """

    name: str
    synonyms: list[str] = []
    description: str
    column: str
    agg: Literal["sum", "mean", "count", "nunique", "min", "max"]
    groupby: str | None = None
    base_filters: dict = Field(default_factory=dict)
    status: Literal["draft", "pending", "approved", "rejected", "deprecated"] = "draft"
    version: int = 1
    created_by: str = "system"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_by: str | None = None
    approved_at: datetime | None = None
    risk: Literal["low", "medium", "high"] = "low"
    source: Literal["auto", "proposed", "manual"] = "auto"
    proposal_id: str | None = None


class MetricProposal(BaseModel):
    """A pending human-approval proposal for a new metric.

    Created by the agent's propose_metric flow, persisted to
    data/catalog/proposals/<uuid>.yaml, and only enters the approved catalog
    after a human calls CatalogService.approve(...).
    """

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metric: MetricDefinition
    question: str
    reason: str
    proposed_by: str = "agent"
    proposed_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["pending", "approved", "rejected"] = "pending"
    review_note: str | None = None


class CatalogVersion(BaseModel):
    """Metadata describing a single snapshot in the version history."""

    version: str
    timestamp: datetime
    count: int
    note: str | None = None