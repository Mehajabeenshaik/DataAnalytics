"""pii_masker.py — PII detection and masking with an encrypted vault.

The vault (pii_vault.db.enc) is a Fernet-encrypted SQLite database.  All
reads and writes go through encryption.EncryptedDB so that plaintext PII
(original names, emails, phone numbers, addresses) is never stored on disk
unencrypted — only the masked/tokenised values appear in the main analytics
database (ecommerce.db.enc).

Key design decisions
--------------------
* _get_or_create_key() in encryption.py is the single source of truth for the
  Fernet key; pii_masker.py does NOT create its own key system.
* PII_VAULT_ENCRYPTED_PATH (config.py) defaults to pii_vault.db.enc, which is
  clearly distinct from a hypothetical plaintext pii_vault.db.
* Every vault operation opens the encrypted file via `with EncryptedDB(...) as
  tmp_db`, performs SQL inside that context, and lets __exit__ re-encrypt and
  clean up the temp file automatically.
"""

import sqlite3
from config import PII_VAULT_ENCRYPTED_PATH
from encryption import EncryptedDB

try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False
    print("WARNING: presidio-analyzer not installed. Run: pip install presidio-analyzer presidio-anonymizer")


VAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS pii_vault (
    customer_id       INTEGER,
    field_name        TEXT,
    original_value    TEXT NOT NULL,
    masked_value      TEXT NOT NULL,
    entity_type       TEXT,
    confidence        REAL,
    PRIMARY KEY (customer_id, field_name)
);
"""

_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is not None:
        return _analyzer
    if not PRESIDIO_AVAILABLE:
        return None
    try:
        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        })
        _analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
    except Exception as e:
        print(f"WARNING: Could not initialize Presidio analyzer: {e}")
        print("Run: python -m spacy download en_core_web_sm")
        return None
    return _analyzer


class PIIMasker:
    """Masks customer PII and stores the original↔masked mapping in an
    encrypted SQLite vault (pii_vault.db.enc).

    All four public methods that touch the vault open it through EncryptedDB
    so the file on disk is always Fernet-encrypted.
    """

    def __init__(self, vault_path: str = PII_VAULT_ENCRYPTED_PATH):
        self.vault_path = vault_path
        self._init_vault()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_vault(self):
        """Ensure the vault schema exists inside the encrypted file."""
        with EncryptedDB(encrypted_path=self.vault_path) as tmp_db:
            conn = sqlite3.connect(tmp_db)
            conn.executescript(VAULT_SCHEMA)
            conn.commit()
            conn.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_text(self, text: str, entities: list[str] | None = None) -> list:
        analyzer = _get_analyzer()
        if analyzer is None:
            return []
        if entities is None:
            entities = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION"]
        return analyzer.analyze(text=text, entities=entities, language="en")

    def mask_customers_batch(self, customers: list[tuple]) -> tuple[list[tuple], int]:
        """Mask a batch of raw customer tuples and persist originals to the
        encrypted vault.

        Returns (masked_list, total_presidio_detections).
        """
        vault_records = []
        masked_list = []
        total_detections = 0

        for cust in customers:
            cid, first, last, email, phone, address, region, city, signup = cust
            cid_str = str(cid).zfill(3)

            scan_text = f"{first} {last} | {email} | {phone} | {address}"
            results = self.scan_text(scan_text)
            total_detections += len(results)

            masked = {
                "first_name": "Customer",
                "last_name": cid_str,
                "email": f"customer.{cid_str}@masked.local",
                "phone": f"+91-XXXXX-X{cid_str}",
                "address": f"[REDACTED], {city}",
            }

            originals = {
                "first_name": first,
                "last_name": last,
                "email": email,
                "phone": phone,
                "address": address,
            }

            for field, original in originals.items():
                entity_type = "KNOWN_PII"
                conf = 1.0
                for r in results:
                    detected = scan_text[r.start:r.end]
                    if detected.lower() in original.lower() or original.lower() in detected.lower():
                        entity_type = r.entity_type
                        conf = r.score
                        break
                vault_records.append((
                    cid, field, original, masked[field], entity_type, conf
                ))

            masked_list.append((
                cid, masked["first_name"], masked["last_name"], masked["email"],
                masked["phone"], masked["address"], region, city, signup,
            ))

        # Write all vault records through the encrypted wrapper in one pass.
        with EncryptedDB(encrypted_path=self.vault_path) as tmp_db:
            conn = sqlite3.connect(tmp_db)
            conn.executemany(
                "INSERT OR REPLACE INTO pii_vault VALUES (?,?,?,?,?,?)",
                vault_records,
            )
            conn.commit()
            conn.close()

        return masked_list, total_detections

    def get_before_after(self, limit: int = 5) -> list[dict]:
        """Return before/after records for the first *limit* customers from the
        encrypted vault."""
        with EncryptedDB(encrypted_path=self.vault_path) as tmp_db:
            conn = sqlite3.connect(tmp_db)
            conn.row_factory = sqlite3.Row
            cids = [r[0] for r in conn.execute(
                "SELECT DISTINCT customer_id FROM pii_vault ORDER BY customer_id LIMIT ?",
                (limit,),
            ).fetchall()]
            if not cids:
                conn.close()
                return []
            placeholders = ",".join("?" * len(cids))
            rows = conn.execute(
                f"SELECT * FROM pii_vault WHERE customer_id IN ({placeholders}) ORDER BY customer_id, field_name",
                cids,
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def vault_stats(self) -> dict:
        """Return aggregate statistics from the encrypted vault."""
        with EncryptedDB(encrypted_path=self.vault_path) as tmp_db:
            conn = sqlite3.connect(tmp_db)
            total = conn.execute("SELECT COUNT(*) FROM pii_vault").fetchone()[0]
            by_entity = conn.execute(
                "SELECT entity_type, COUNT(*), ROUND(AVG(confidence),3) FROM pii_vault GROUP BY entity_type"
            ).fetchall()
            conn.close()
        return {
            "total_records": total,
            "by_entity": [(r[0], r[1], r[2]) for r in by_entity],
        }

    def clear_vault(self):
        """Delete all records from the encrypted vault (used before re-seeding)."""
        with EncryptedDB(encrypted_path=self.vault_path) as tmp_db:
            conn = sqlite3.connect(tmp_db)
            conn.execute("DELETE FROM pii_vault")
            conn.commit()
            conn.close()
