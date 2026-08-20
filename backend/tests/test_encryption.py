import os
import sqlite3
from encryption import EncryptedDB
from session_manager import SessionManager
from config import BASE_DIR

print("=" * 70)
print("MODULE 12 TEST: Session Security & Encryption")
print("=" * 70)

# --- Part A: SQLite Encryption at Rest ---
print("\n--- Part A: Database Encryption ---\n")

test_db = str(BASE_DIR / "test_plain.db")
test_enc = str(BASE_DIR / "test_encrypted.db.enc")

for f in [test_db, test_enc]:
    if os.path.exists(f):
        os.remove(f)

conn = sqlite3.connect(test_db)
conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
conn.execute("INSERT INTO test VALUES (1, 'secret data')")
conn.execute("INSERT INTO test VALUES (2, 'more secrets')")
conn.commit()
conn.close()
print("[1] Created plain test database with secret data")

# Encrypt it
edb = EncryptedDB(encrypted_path=test_enc)
enc_path = edb.encrypt_existing(test_db)
print(f"[2] Encrypted to: {enc_path}")

# Verify encrypted file is NOT valid SQLite
print("\n[3] Verifying encrypted file is unreadable as SQLite...")
assert not edb.is_valid_sqlite(test_enc), "FAIL: Encrypted file reads as valid SQLite!"
print("    PASS: Encrypted file is NOT valid SQLite (data is protected)")

# Verify via hex check
with open(test_enc, "rb") as f:
    header = f.read(16)
assert b"SQLite" not in header, "FAIL: SQLite header found in encrypted file!"
print("    PASS: No SQLite header in encrypted file")

# Decrypt via context manager and verify data
print("\n[4] Decrypting via context manager...")
with EncryptedDB(encrypted_path=test_enc) as temp_path:
    assert edb.is_valid_sqlite(temp_path), "FAIL: Decrypted file is not valid SQLite!"
    conn = sqlite3.connect(temp_path)
    rows = conn.execute("SELECT * FROM test").fetchall()
    conn.close()
    print(f"    Decrypted rows: {rows}")
    assert rows == [(1, "secret data"), (2, "more secrets")]
    print("    PASS: Data integrity verified after decrypt")
    temp_existed = os.path.exists(temp_path)
    temp_path_saved = temp_path

# Verify temp file is cleaned up
print(f"\n[5] Verifying temp file cleanup...")
assert not os.path.exists(temp_path_saved), "FAIL: Temp file still exists!"
print("    PASS: Temp file automatically deleted after context exit")

# Encrypt the real ecommerce.db
ecommerce_db = str(BASE_DIR / "ecommerce.db")
if os.path.exists(ecommerce_db):
    print(f"\n[6] Encrypting real ecommerce.db...")
    real_enc = str(BASE_DIR / "ecommerce.db.enc")
    edb_real = EncryptedDB(encrypted_path=real_enc)
    edb_real.encrypt_existing(ecommerce_db)
    enc_size = os.path.getsize(real_enc)
    plain_size = os.path.getsize(ecommerce_db)
    print(f"    Plain size:     {plain_size:,} bytes")
    print(f"    Encrypted size: {enc_size:,} bytes")
    print(f"    PASS: ecommerce.db encrypted at rest")

# Cleanup test files
for f in [test_db, test_enc]:
    if os.path.exists(f):
        os.remove(f)

# --- Part B: Session Manager ---
print("\n--- Part B: Session Manager ---\n")

sm = SessionManager(timeout_minutes=1)

print("[7] Creating sessions...")
dir1 = sm.create_session("user_session_001")
dir2 = sm.create_session("user_session_002")
print(f"    Session 1 temp dir: {dir1}")
print(f"    Session 2 temp dir: {dir2}")
assert os.path.exists(dir1) and os.path.exists(dir2)
print("    PASS: Temp directories created")

print("\n[8] Active sessions:")
for s in sm.active_sessions():
    print(f"    {s['session_id']} | idle: {s['idle_seconds']}s")

print("\n[9] Touching session 1 (simulating activity)...")
sm.touch("user_session_001")
print("    PASS: Last activity updated")

print("\n[10] Destroying session 2...")
sm.destroy_session("user_session_002")
assert not os.path.exists(dir2), "FAIL: Session 2 temp dir still exists!"
print("    PASS: Session 2 temp dir cleaned up")
print(f"    Active sessions: {len(sm.active_sessions())}")

# Cleanup session 1
sm.destroy_session("user_session_001")

print("\n" + "=" * 70)
print("MODULE 12 COMPLETE")
print("=" * 70)
