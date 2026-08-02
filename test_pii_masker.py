"""test_pii_masker.py — PII masking and encrypted vault tests.

Tests cover:
  1. PII masking via PIIMasker.mask_customers_batch()
  2. Vault stats after masking
  3. SECURITY: plaintext PII must NOT appear in the raw vault file
"""
import os
import pytest
import tempfile

from pii_masker import PIIMasker


# ── PII masking smoke tests ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def masker():
    """Return a PIIMasker instance."""
    return PIIMasker()


def test_masking_produces_masked_records(masker):
    """mask_customers_batch() returns masked records with @masked.local emails."""
    fake_customers = [
        (1, "John", "Smith", "john.smith@example.com", "+91-99999-99999",
         "123 Main St, Mumbai", "West", "Mumbai", "2024-01-01"),
        (2, "Jane", "Doe", "jane.doe@example.com", "+91-88888-88888",
         "456 Oak Ave, Delhi", "North", "Delhi", "2024-02-01"),
    ]
    masked, detections = masker.mask_customers_batch(fake_customers)
    assert len(masked) == 2
    # Masked emails should contain @masked.local
    for cust in masked:
        email = cust[3]  # email field
        assert "@masked.local" in email, (
            f"Masked email does not contain @masked.local: {email}"
        )


def test_vault_stats_has_records(masker):
    """vault_stats() reports records after masking."""
    stats = masker.vault_stats()
    assert stats["total_records"] > 0, "PII vault reported zero records"


def test_masked_customer_name_format(masker):
    """Masked customer names should follow the 'Customer NNN' pattern."""
    fake_customers = [
        (999, "Test", "User", "test.user@example.com", "+91-00000-00000",
         "1 Test St", "West", "Mumbai", "2024-01-01"),
    ]
    masked, _ = masker.mask_customers_batch(fake_customers)
    name = masked[0][1] + " " + masked[0][2]  # first + last
    assert "Customer" in name, f"Masked name doesn't contain 'Customer': {name}"


# ── SECURITY TEST: plaintext PII must NOT appear in the raw vault file ──

def test_vault_file_is_encrypted_at_rest():
    """Write a known fake PII email into a fresh vault, then read the raw
    bytes of the .enc file and assert the plaintext email is NOT present.

    This directly verifies that EncryptedDB is wrapping the vault file and
    that plaintext PII never hits disk.
    """
    FAKE_EMAIL = "security.test.victim@plaintext-should-not-appear.com"

    with tempfile.NamedTemporaryFile(suffix=".db.enc", delete=False) as f:
        tmp_vault_path = f.name
    os.unlink(tmp_vault_path)

    try:
        masker = PIIMasker(vault_path=tmp_vault_path)

        fake_customer = (
            9001,
            "Fake",
            "Victim",
            FAKE_EMAIL,
            "+91-00000-00000",
            "1 Test Street, Mumbai",
            "West",
            "Mumbai",
            "2024-01-01",
        )

        masker.mask_customers_batch([fake_customer])

        assert os.path.exists(tmp_vault_path), "Vault encrypted file was not created."
        with open(tmp_vault_path, "rb") as f:
            raw_bytes = f.read()

        assert len(raw_bytes) > 0, "Vault file is empty."

        assert FAKE_EMAIL.encode() not in raw_bytes, (
            f"SECURITY FAILURE: plaintext email '{FAKE_EMAIL}' found in vault file. "
            f"The vault is NOT encrypted at rest."
        )

        assert b"security.test.victim" not in raw_bytes, (
            "SECURITY FAILURE: partial plaintext email fragment found in vault."
        )
        assert b"plaintext-should-not-appear" not in raw_bytes, (
            "SECURITY FAILURE: partial plaintext domain fragment found in vault."
        )

    finally:
        if os.path.exists(tmp_vault_path):
            os.unlink(tmp_vault_path)