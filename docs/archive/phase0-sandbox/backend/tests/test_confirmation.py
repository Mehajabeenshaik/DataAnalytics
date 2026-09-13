from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.policy import ConfirmationManager, get_confirmation_manager

client = TestClient(app)


def test_read_only_ask_no_confirmation():
    res = client.post(
        "/ask",
        json={"question": "What is the total revenue?"},
        headers={"X-API-Key": "key_tenant_a_123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "completed"
    assert "confirmation_token" not in data


def test_consequential_plan_requires_confirmation():
    conf_mgr = get_confirmation_manager()
    plan_dict = {"plan_type": "propose_metric", "proposal": {"name": "new_metric"}}
    req = conf_mgr.create_request("tenant_a", "Propose new metric", "propose_metric", plan_dict)

    assert req.token.startswith("confirm_")
    assert req.status == "pending"

    # Test confirmation endpoint
    res_confirm = client.post(
        "/ask/confirm",
        json={"confirmation_token": req.token, "approve": True},
        headers={"X-API-Key": "key_tenant_a_123"},
    )
    assert res_confirm.status_code == 200
    data_confirm = res_confirm.json()
    assert data_confirm["status"] == "confirmed_and_executed"
