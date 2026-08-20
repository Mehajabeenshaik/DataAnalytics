import sqlite3
import json
from datetime import datetime, timezone
from config import AUDIT_DB_PATH


AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    username    TEXT NOT NULL,
    role        TEXT NOT NULL,
    action_type TEXT NOT NULL,
    details     TEXT,
    ip_address  TEXT,
    tenant_id   TEXT
);
"""

# Indexes are created separately AFTER the tenant_id migration so that
# pre-existing audit_log tables (without tenant_id) don't break.
AUDIT_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);
"""

ACTION_TYPES = {
    "LOGIN", "LOGOUT", "QUERY", "METRIC_RESOLVE", "DATA_RESEED", "PII_ACCESS", "ERROR",
    "METRIC_PROPOSE", "METRIC_APPROVE", "METRIC_REJECT",
}


def init_audit_db(db_path: str = AUDIT_DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.executescript(AUDIT_SCHEMA)
    # Migration: add tenant_id column to pre-existing audit_log tables.
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
        if "tenant_id" not in cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN tenant_id TEXT")
    except sqlite3.OperationalError:
        pass
    # Create all indexes AFTER the tenant_id migration so pre-existing
    # tables (without tenant_id) don't break CREATE INDEX statements.
    conn.executescript(AUDIT_INDEXES)
    conn.commit()
    conn.close()


def log_action(
    username: str,
    role: str,
    action_type: str,
    details: dict | None = None,
    ip_address: str = "127.0.0.1",
    db_path: str = AUDIT_DB_PATH,
    tenant_id: str | None = None,
):
    if action_type not in ACTION_TYPES:
        raise ValueError(f"Invalid action_type '{action_type}'. Must be one of: {ACTION_TYPES}")

    init_audit_db(db_path)

    safe_details = None
    if details:
        safe = {k: v for k, v in details.items() if k not in ("raw_data", "pii", "password", "token")}
        safe_details = json.dumps(safe, default=str)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO audit_log (timestamp, username, role, action_type, details, ip_address, tenant_id) VALUES (?,?,?,?,?,?,?)",
        (
            datetime.now(timezone.utc).isoformat(),
            username,
            role,
            action_type,
            safe_details,
            ip_address,
            tenant_id,
        ),
    )
    conn.commit()
    conn.close()


def get_audit_logs(
    username: str | None = None,
    action_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str = AUDIT_DB_PATH,
    tenant_id: str | None = None,
) -> list[dict]:
    init_audit_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []

    if username:
        query += " AND username = ?"
        params.append(username)
    if action_type:
        query += " AND action_type = ?"
        params.append(action_type)
    if tenant_id:
        query += " AND tenant_id = ?"
        params.append(tenant_id)

    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        entry = dict(r)
        if entry["details"]:
            entry["details"] = json.loads(entry["details"])
        results.append(entry)
    return results


def export_audit(
    tenant_id: str,
    days: int = 30,
    db_path: str = AUDIT_DB_PATH,
) -> list[dict]:
    """Export audit records for a single tenant over the last N days.

    This is the ONLY way admins should read audit data for a tenant — it
    guarantees tenant isolation by construction (the WHERE clause always
    filters on tenant_id).
    """
    init_audit_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE tenant_id = ? AND timestamp >= ? ORDER BY id DESC",
        (tenant_id, cutoff),
    ).fetchall()
    conn.close()

    results = []
    for r in rows:
        entry = dict(r)
        if entry["details"]:
            entry["details"] = json.loads(entry["details"])
        results.append(entry)
    return results


def get_audit_stats(db_path: str = AUDIT_DB_PATH) -> dict:
    init_audit_db(db_path)
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    by_action = conn.execute(
        "SELECT action_type, COUNT(*) FROM audit_log GROUP BY action_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_user = conn.execute(
        "SELECT username, COUNT(*) FROM audit_log GROUP BY username ORDER BY COUNT(*) DESC"
    ).fetchall()
    conn.close()
    return {
        "total_entries": total,
        "by_action": [(r[0], r[1]) for r in by_action],
        "by_user": [(r[0], r[1]) for r in by_user],
    }
