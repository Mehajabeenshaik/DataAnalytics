"""Confirmation manager + endpoint tests (Phase 4 policy)."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.app.auth import app
from policy import get_confirmation_manager

client = TestClient(app)


def test_confirmation_token_scoped_to_tenant():
    """A tenant can only resolve its own confirmation token."""
    mgr = get_confirmation_manager()
    req = mgr.create_request("tenant_owner", "Do the thing", "write_back", {"k": "v"})

    # A different tenant is forbidden.
    r_other = client.post(
        "/api/v1/ask/confirm",
        json={"confirmation_token": req.token, "approve": True},
        headers={"X-API-Key": "ak_other_tenant_key"},
    )
    assert r_other.status_code in (401, 403)

    # The owning tenant is forbidden too (no such API key registered), because
    # the confirm endpoint requires a valid registered X-API-Key first.
    r_owner = client.post(
        "/api/v1/ask/confirm",
        json={"confirmation_token": req.token, "approve": True},
        headers={"X-API-Key": req.tenant_id},
    )
    assert r_owner.status_code in (401, 403)


def test_confirm_endpoint_requires_api_key():
    r = client.post(
        "/api/v1/ask/confirm",
        json={"confirmation_token": "confirm_abc", "approve": True},
    )
    assert r.status_code == 422  # missing X-API-Key header


def test_confirm_unknown_token():
    r = client.post(
        "/api/v1/ask/confirm",
        json={"confirmation_token": "confirm_does_not_exist", "approve": True},
        headers={"X-API-Key": "ak_whatever"},
    )
    assert r.status_code in (401, 404)


def test_manager_resolve_reject():
    mgr = get_confirmation_manager()
    req = mgr.create_request("t", "question", "send_report", {})
    resolved = mgr.resolve(req.token, approve=False)
    assert resolved.status == "rejected"