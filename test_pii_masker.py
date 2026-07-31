"""test_pii_masker.py — PII masking and encrypted vault tests.

Tests cover:
  1. Original script-mode PII masking smoke tests (preserved as pytest
     functions so they continue to appear in test output).
  2. SECURITY: After writing a known PII value to the vault, reading the
     raw bytes of the .enc file on disk must NOT contain the plaintext
     PII string — confirming that the vault is genuinely encrypted at rest.
"""
import os
import pytest
import tempfile

from data_layer import init_db, query_enriched
from pii_masker import PIIMasker


# ── Existing behaviour: basic masking smoke tests ───────────────────────

@pytest.fixture(scope="module", autouse=True)
def seeded_db():
    """Seed the database once for all tests in this module."""
    init_db(force_reseed=True)


def test_masking_produces_masked_records():
    """get_before_after() returns records and every masked email is @masked.local."""
    masker = PIIMasker()
    records = masker.get_before_after(limit=5)
    assert records, "vault returned no before/after records"
    email_records = [r for r in records if r["field_name"] == "email"]
    for r in email_records:
        assert "@masked.local" in r["masked_value"], (
            f"Masked email does not contain @masked.local: {r['masked_value']}"
        )


def test_vault_stats_has_records():
    """vault_stats() reports a non-zero total after seeding."""
    masker = PIIMasker()
    stats = masker.vault_stats()
    assert stats["total_records"] > 0, "PII vault reported zero records after seeding"


def test_orders_enriched_contains_only_masked_data():
    """The orders_enriched view must not expose raw PII patterns."""
    df = query_enriched()
    raw_pii_pattern = r"@gmail|@yahoo|@outlook|Aarav|Vivaan|Sharma|Patel"
    raw_found = df["customer_name"].str.contains(raw_pii_pattern, case=False, regex=True)
    assert not raw_found.any(), (
        "FAIL: Raw PII found in orders_enriched — masking is broken."
    )


def test_masked_customer_name_format():
    """All customer names in the view must follow the 'Customer NNN' pattern."""
    df = query_enriched()
    # Every masked name is 'Customer <zero-padded-id>'
    bad_names = df["customer_name"][
        ~df["customer_name"].str.match(r"^Customer \d+$")
    ]
    assert bad_names.empty, (
        f"Found customer names that don't match 'Customer NNN' pattern: "
        f"{bad_names.unique()[:5].tolist()}"
    )


# ── SECURITY TEST: plaintext PII must NOT appear in the raw vault file ──

def test_vault_file_is_encrypted_at_rest():
    """Write a known fake PII email into a fresh vault, then read the raw
    bytes of the .enc file and assert the plaintext email is NOT present.

    This directly verifies that EncryptedDB is wrapping the vault file and
    that plaintext PII never hits disk — the core requirement of Issue 1.
    """
    FAKE_EMAIL = "security.test.victim@plaintext-should-not-appear.com"

    # Use a dedicated temp file so this test is isolated from the main vault.
    with tempfile.NamedTemporaryFile(suffix=".db.enc", delete=False) as f:
        tmp_vault_path = f.name
    os.unlink(tmp_vault_path)  # Remove so EncryptedDB starts fresh.

    try:
        masker = PIIMasker(vault_path=tmp_vault_path)

        # Build a minimal customer tuple and inject our known email.
        fake_customer = (
            9001,          # customer_id
            "Fake",        # first_name
            "Victim",      # last_name
            FAKE_EMAIL,    # email — this is the PII we're tracking
            "+91-00000-00000",  # phone
            "1 Test Street, Mumbai",  # address
            "West",        # region
            "Mumbai",      # city
            "2024-01-01",  # signup_date
        )

        masker.mask_customers_batch([fake_customer])

        # ── Core assertion ──────────────────────────────────────────────
        # Read the raw bytes of the on-disk .enc file.
        assert os.path.exists(tmp_vault_path), (
            "Vault encrypted file was not created on disk."
        )
        with open(tmp_vault_path, "rb") as f:
            raw_bytes = f.read()

        assert len(raw_bytes) > 0, "Vault file is empty — nothing was written."

        # The plaintext email must NOT appear anywhere in the raw bytes.
        assert FAKE_EMAIL.encode() not in raw_bytes, (
            f"SECURITY FAILURE: plaintext email '{FAKE_EMAIL}' was found in "
            f"the raw bytes of the encrypted vault file. "
            f"The vault is NOT encrypted at rest."
        )

        # Paranoia check: verify partial fragments of the email also absent.
        assert b"security.test.victim" not in raw_bytes, (
            "SECURITY FAILURE: partial plaintext email fragment found in vault."
        )
        assert b"plaintext-should-not-appear" not in raw_bytes, (
            "SECURITY FAILURE: partial plaintext domain fragment found in vault."
        )

    finally:
        if os.path.exists(tmp_vault_path):
            os.unlink(tmp_vault_path)


# ── Preserve original script-mode output as a helper (not a test) ───────

def _run_legacy_print_output():
    """Reproduce the original script-style stdout output for backward compat."""
    masker = PIIMasker()

    print("=" * 70)
    print("MODULE 8 TEST: PII Detection & Masking with Microsoft Presidio")
    print("=" * 70)

    print("\n" + "=" * 70)
    print("BEFORE / AFTER PII MASKING (First 5 Customers)")
    print("=" * 70)
    records = masker.get_before_after(limit=5)
    current_cid = None
    for r in records:
        if r["customer_id"] != current_cid:
            current_cid = r["customer_id"]
            print(f"\n--- Customer {current_cid} ---")
        print(f"  {r['field_name']:15s} | ORIGINAL: {r['original_value']:45s}")
        print(f"  {'':15s} | MASKED:   {r['masked_value']:45s}")
        print(f"  {'':15s} | Presidio: {r['entity_type']} (conf: {r['confidence']:.2f})")

    print("\n" + "=" * 70)
    print("PII VAULT STATISTICS")
    print("=" * 70)
    stats = masker.vault_stats()
    print(f"Total vault records: {stats['total_records']}")
    for entity, count, avg_conf in stats["by_entity"]:
        print(f"  {entity:20s} | {count:4d} records | avg confidence: {avg_conf}")

    print("\n" + "=" * 70)
    print("ORDERS_ENRICHED VIEW (proving only masked data is visible)")
    print("=" * 70)
    df = query_enriched()
    sample_cols = ["customer_name", "customer_email", "customer_phone", "customer_address", "customer_region"]
    print(df[sample_cols].drop_duplicates().head(10).to_string(index=False))
