"""
Pydantic models for the enterprise identity & isolation layer.

Phase 3 of the DataAnalytics governed-agent roadmap.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Org(BaseModel):
    """A company / organization that owns one or more tenants."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["active", "suspended"] = "active"


class Tenant(BaseModel):
    """A tenant — the isolation boundary for data, catalog, cache, audit."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["active", "suspended"] = "active"


class User(BaseModel):
    """A user account (identity)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    display_name: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Membership(BaseModel):
    """Links a user to an org or tenant with a role."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    tenant_id: str | None = None
    org_id: str | None = None
    role: Literal["owner", "admin", "analyst", "viewer"] = "analyst"


class AuthContext(BaseModel):
    """The identity + isolation context attached to every request.

    Every ask(), catalog, and audit call receives this context and uses
    tenant_id for isolation. auth_method records how the identity was
    established (api_key | jwt | oidc).
    """

    user_id: str | None = None
    tenant_id: str
    org_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    auth_method: Literal["api_key", "jwt", "oidc"] = "api_key"

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def is_admin(self) -> bool:
        return self.has_role("admin") or self.has_role("owner")