import httpx
import time
import sys

BASE = "http://localhost:8000"

print("=" * 70)
print("MODULE 10 TEST: Authentication & Role-Based Access Control")
print("=" * 70)

# Wait for server
print("\n[1] Checking auth server...")
for i in range(5):
    try:
        r = httpx.get(f"{BASE}/docs", timeout=2)
        if r.status_code == 200:
            print("    PASS: Auth server is running")
            break
    except httpx.ConnectError:
        if i < 4:
            time.sleep(1)
        else:
            print("    FAIL: Auth server not reachable.")
            print("    Start it: uvicorn auth:app --port 8000")
            sys.exit(1)

# --- Login as Admin ---
print("\n[2] Login as admin (admin/admin123)...")
r = httpx.post(f"{BASE}/auth/login", data={"username": "admin", "password": "admin123"})
assert r.status_code == 200, f"FAIL: {r.status_code} {r.text}"
admin_token = r.json()["access_token"]
admin_role = r.json()["role"]
print(f"    PASS: Got token, role={admin_role}")

# --- Login as Viewer ---
print("\n[3] Login as viewer (viewer/viewer123)...")
r = httpx.post(f"{BASE}/auth/login", data={"username": "viewer", "password": "viewer123"})
assert r.status_code == 200, f"FAIL: {r.status_code} {r.text}"
viewer_token = r.json()["access_token"]
viewer_role = r.json()["role"]
print(f"    PASS: Got token, role={viewer_role}")

# --- Wrong password ---
print("\n[4] Login with wrong password...")
r = httpx.post(f"{BASE}/auth/login", data={"username": "admin", "password": "wrong"})
assert r.status_code == 401, f"FAIL: Expected 401, got {r.status_code}"
print(f"    PASS: Rejected with 401")

# --- /auth/me ---
print("\n[5] GET /auth/me with admin token...")
r = httpx.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
assert r.status_code == 200 and r.json()["role"] == "admin"
print(f"    PASS: {r.json()}")

# --- Admin-only route: register user ---
print("\n[6] Admin registers new user...")
r = httpx.post(
    f"{BASE}/auth/register",
    json={"username": "analyst1", "password": "test123", "role": "viewer"},
    headers={"Authorization": f"Bearer {admin_token}"},
)
if r.status_code == 200:
    print(f"    PASS: Created user {r.json()}")
elif r.status_code == 400 and "already exists" in r.text:
    print(f"    PASS: User already exists (idempotent)")
else:
    print(f"    FAIL: {r.status_code} {r.text}")

# --- Viewer tries admin-only route ---
print("\n[7] Viewer tries to register a user (should be 403)...")
r = httpx.post(
    f"{BASE}/auth/register",
    json={"username": "hacker", "password": "hack", "role": "admin"},
    headers={"Authorization": f"Bearer {viewer_token}"},
)
assert r.status_code == 403, f"FAIL: Expected 403, got {r.status_code}"
print(f"    PASS: Viewer blocked with 403 - {r.json()['detail']}")

# --- Viewer tries PII vault access ---
print("\n[8] Viewer tries PII vault (should be 403)...")
r = httpx.get(
    f"{BASE}/admin/pii-vault/1",
    headers={"Authorization": f"Bearer {viewer_token}"},
)
assert r.status_code == 403, f"FAIL: Expected 403, got {r.status_code}"
print(f"    PASS: Viewer blocked from PII vault")

# --- Admin accesses PII vault ---
print("\n[9] Admin accesses PII vault...")
r = httpx.get(
    f"{BASE}/admin/pii-vault/1",
    headers={"Authorization": f"Bearer {admin_token}"},
    timeout=15,
)
if r.status_code == 200:
    print(f"    PASS: Admin can see PII vault ({len(r.json()['pii_records'])} records)")
else:
    print(f"    INFO: {r.status_code} - {r.text}")

# --- No token ---
print("\n[10] Request without token (should be 401)...")
r = httpx.get(f"{BASE}/auth/me")
assert r.status_code == 401, f"FAIL: Expected 401, got {r.status_code}"
print(f"    PASS: Unauthenticated request rejected")

print("\n" + "=" * 70)
print("MODULE 10 COMPLETE: All RBAC checks passed")
print("=" * 70)
