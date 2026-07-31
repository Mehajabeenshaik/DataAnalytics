import os
import tempfile
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet
from config import DB_ENCRYPTION_KEY, BASE_DIR


def _get_or_create_key() -> bytes:
    """Return the Fernet encryption key, creating and persisting one if absent.

    Key resolution order:
      1. DB_ENCRYPTION_KEY env var (explicit, preferred for production).
      2. .db.key file in BASE_DIR (auto-generated on first run; must be backed up).
    """
    if DB_ENCRYPTION_KEY:
        return DB_ENCRYPTION_KEY.encode()

    key_file = BASE_DIR / ".db.key"
    if key_file.exists():
        return key_file.read_bytes().strip()

    key = Fernet.generate_key()
    key_file.write_bytes(key)
    print(f"WARNING: Generated new encryption key at {key_file}")
    print("         Secure this file! Without it, encrypted data is unrecoverable.")
    return key


class EncryptedDB:
    """Context-manager wrapper that transparently decrypts an on-disk database
    to a temporary file for use, then re-encrypts and removes the temp file
    on exit.

    The same class (and the same Fernet key via _get_or_create_key) is used
    for both ecommerce.db.enc and pii_vault.db.enc so that a single key
    protects all sensitive data stores — no second key system is introduced.

    Usage::

        with EncryptedDB(encrypted_path="/path/to/file.db.enc") as tmp_db_path:
            conn = sqlite3.connect(tmp_db_path)
            ...
            conn.close()
        # temp file is deleted and encrypted file is updated on exit
    """

    def __init__(self, encrypted_path: str | None = None):
        self.encrypted_path = encrypted_path or str(BASE_DIR / "ecommerce.db.enc")
        self.fernet = Fernet(_get_or_create_key())
        self._temp_path = None

    def __enter__(self) -> str:
        fd, self._temp_path = tempfile.mkstemp(suffix=".db", prefix="analytics_")
        os.close(fd)

        if os.path.exists(self.encrypted_path):
            with open(self.encrypted_path, "rb") as f:
                encrypted_data = f.read()
            if encrypted_data:
                decrypted = self.fernet.decrypt(encrypted_data)
                with open(self._temp_path, "wb") as f:
                    f.write(decrypted)

        return self._temp_path

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._temp_path and os.path.exists(self._temp_path):
                with open(self._temp_path, "rb") as f:
                    raw = f.read()
                encrypted = self.fernet.encrypt(raw)
                with open(self.encrypted_path, "wb") as f:
                    f.write(encrypted)
        finally:
            if self._temp_path and os.path.exists(self._temp_path):
                os.remove(self._temp_path)
                self._temp_path = None

    def encrypt_existing(self, plain_db_path: str):
        """One-shot: encrypt an existing plaintext SQLite file and write to
        self.encrypted_path.  The source file is NOT deleted by this method."""
        with open(plain_db_path, "rb") as f:
            raw = f.read()
        encrypted = self.fernet.encrypt(raw)
        with open(self.encrypted_path, "wb") as f:
            f.write(encrypted)
        return self.encrypted_path

    def is_valid_sqlite(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                header = f.read(16)
            return header[:6] == b"SQLite"
        except Exception:
            return False
