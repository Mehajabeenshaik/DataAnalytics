import os
import tempfile
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet
from config import DB_ENCRYPTION_KEY, BASE_DIR


def _get_or_create_key() -> bytes:
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
