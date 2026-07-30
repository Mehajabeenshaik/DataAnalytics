from audit_logger import log_action, get_audit_logs, get_audit_stats

print("=" * 70)
print("MODULE 11 TEST: Audit Logging")
print("=" * 70)

# Simulate a sequence of auditable actions
log_action("admin", "admin", "LOGIN", {"method": "password"})
log_action("viewer", "viewer", "LOGIN", {"method": "password"})
log_action("viewer", "viewer", "QUERY", {
    "question": "What is total revenue by region?",
    "metric_selected": "total_revenue",
    "dimensions": ["customer_region"],
    "result_row_count": 4,
})
log_action("admin", "admin", "METRIC_RESOLVE", {
    "metric": "order_count",
    "dimensions": ["product_category"],
    "filters": {"order_status": "completed"},
    "result_row_count": 5,
})
log_action("admin", "admin", "PII_ACCESS", {
    "customer_id": 42,
    "fields_accessed": ["first_name", "email"],
})
log_action("admin", "admin", "DATA_RESEED", {"reason": "demo reset"})
log_action("viewer", "viewer", "QUERY", {
    "question": "Show top products",
    "metric_selected": "top_products",
    "result_row_count": 10,
    "raw_data": "THIS SHOULD BE STRIPPED",
    "pii": "THIS SHOULD ALSO BE STRIPPED",
})
log_action("viewer", "viewer", "LOGOUT", {})

print("\n[1] Logged 8 sample actions")

# Query all logs
print("\n[2] All audit logs:")
logs = get_audit_logs(limit=20)
for entry in logs:
    details_str = str(entry['details'])[:60] if entry['details'] else ""
    print(f"    {entry['timestamp'][:19]} | {entry['username']:10s} | {entry['action_type']:15s} | {details_str}")

# Verify sensitive fields stripped
print("\n[3] Verifying sensitive fields are stripped...")
for entry in logs:
    if entry["details"]:
        assert "raw_data" not in entry["details"], "FAIL: raw_data found in audit log!"
        assert "pii" not in entry["details"], "FAIL: pii found in audit log!"
        assert "password" not in entry["details"], "FAIL: password found in audit log!"
print("    PASS: No raw_data, pii, or password fields in any log entry")

# Filter by user
print("\n[4] Logs filtered for 'viewer' only:")
viewer_logs = get_audit_logs(username="viewer")
for entry in viewer_logs:
    print(f"    {entry['action_type']:15s} | {str(entry['details'])[:60]}")

# Stats
print("\n[5] Audit stats:")
stats = get_audit_stats()
print(f"    Total entries: {stats['total_entries']}")
print(f"    By action: {stats['by_action']}")
print(f"    By user:   {stats['by_user']}")

print("\n" + "=" * 70)
print("MODULE 11 COMPLETE")
print("=" * 70)
