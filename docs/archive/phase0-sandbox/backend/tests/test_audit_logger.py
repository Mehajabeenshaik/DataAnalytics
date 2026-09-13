import os
import json
import tempfile
from backend.app.audit_logger import log_entry, get_recent, AUDIT_LOG_PATH


def test_audit_log_write_and_read(tmp_path, monkeypatch):
    test_log = tmp_path / "test_audit.log"
    monkeypatch.setattr("backend.app.audit_logger.AUDIT_LOG_PATH", str(test_log))

    entry = {
        "timestamp": "2026-09-11T20:00:00Z",
        "question": "What is total revenue?",
        "plan": {"plan_type": "single_metric"},
        "verification": {"ok": True, "confidence": "high", "flags": []},
    }

    log_entry(entry)

    assert test_log.exists()
    recent = get_recent(limit=5)
    assert len(recent) == 1
    assert recent[0]["question"] == "What is total revenue?"
