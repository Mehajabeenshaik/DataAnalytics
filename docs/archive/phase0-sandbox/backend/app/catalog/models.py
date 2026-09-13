from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List

class MetricDefinition(BaseModel):
    name: str = Field(..., description="Unique metric identifier")
    tenant_id: str = Field(default="default", description="Tenant ID owning this metric")
    description: str = Field(..., description="Human‑readable description")
    synonyms: List[str] = Field(default_factory=list, description="Alternative names for the metric")
    sql_template: str = Field(..., description="SQL expression used by the deterministic executor")
    allowed_filters: List[str] = Field(default_factory=list, description="Columns that may be used as filters")
    version: int = Field(default=1, description="Schema version of the metric definition")
    status: str = Field(..., description="One of: approved, proposed, rejected")

class MetricProposal(BaseModel):
    name: str = Field(..., description="Proposed metric identifier")
    tenant_id: str = Field(default="default", description="Tenant ID submitting proposal")
    description: str = Field(..., description="Human‑readable description")
    synonyms: List[str] = Field(default_factory=list, description="Alternative names for the metric")
    sql_template: str = Field(..., description="SQL expression for the metric (kept secret from planner)")
    allowed_filters: List[str] = Field(default_factory=list, description="Columns that may be used as filters")
    version: int = Field(default=1, description="Schema version of the metric definition")
