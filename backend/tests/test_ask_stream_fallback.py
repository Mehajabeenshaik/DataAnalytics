"""Regression: /api/v1/ask/stream must degrade gracefully when the primary
LLM provider fails to initialise.

Before the fix, the except-fallback branch referenced FallbackLLMProvider
without importing it, so the handler itself raised NameError and the stream
collapsed into the generic "Query failed" error event — defeating the whole
point of the try/except. After the fix, the fallback provider is constructed,
the planner receives its output, and the stream completes with a structured
final event (a graceful decline), never an error event caused by setup.
"""
import io

import pytest
from fastapi.testclient import TestClient

DEMO_KEY = "ak_demo_key_12345"
CSV = "order_id,revenue\n1,100\n2,200\n3,300\n"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-not-for-prod-32chars-min")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    import backend.app.auth as auth_mod

    db_path = tmp_path / "auth.db"
    if db_path.exists():
        db_path.unlink()
    monkeypatch.setattr(auth_mod, "AUTH_DB_PATH", str(db_path))

    import backend.app.main as app_module  # noqa: F401  (wires routers)
    from backend.app.auth import init_auth_db

    init_auth_db()

    from tenant import init_tenant_db  # seeds the demo widget API key

    init_tenant_db()
    return TestClient(app_module.app)


def _make_session_with_dataset(client):
    s = client.post("/api/v1/session", headers={"X-API-Key": DEMO_KEY})
    assert s.status_code == 200, s.text
    session_id = s.json()["session_id"]
    up = client.post(
        "/api/v1/upload",
        headers={"X-API-Key": DEMO_KEY},
        files={"file": ("sales.csv", io.BytesIO(CSV.encode()), "text/csv")},
        data={"session_id": session_id},
    )
    assert up.status_code == 200, up.text
    return session_id


def test_ask_stream_falls_back_when_provider_init_fails(client, monkeypatch):
    import backend.app.api_widget as aw

    session_id = _make_session_with_dataset(client)

    def _boom(provider=None):
        raise RuntimeError("primary LLM unavailable")

    monkeypatch.setattr(aw, "get_provider", _boom)

    class FakeFallback:
        """Stands in for FallbackLLMProvider with a working generate()."""

        def provider_name(self) -> str:
            return "fake-fallback"

        def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
            # Not valid planner JSON on purpose: agent_phase2 degrades this to
            # a no_match plan and synthesizes a graceful decline answer.
            return "fallback-unavailable"

    monkeypatch.setattr(aw, "FallbackLLMProvider", FakeFallback)

    r = client.post(
        "/api/v1/ask/stream",
        headers={"X-API-Key": DEMO_KEY},
        json={"session_id": session_id, "question": "What is total revenue?"},
    )
    assert r.status_code == 200, r.text

    body = r.text
    assert '"final"' in body, f"expected a final event in stream, got:\n{body}"
    assert '"error"' not in body, f"stream emitted an error event:\n{body}"
