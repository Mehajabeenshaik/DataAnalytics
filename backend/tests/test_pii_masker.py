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


# ── Analyzer init must survive spaCy's SystemExit (process-kill guard) ─────
#
# When the en_core_web_sm model is missing, Presidio's NlpEngineProvider tries
# to auto-download it; spacy.cli.download.download_model() then calls
# sys.exit(returncode), which raises SystemExit. SystemExit derives from
# BaseException, NOT Exception, so `except Exception` does not catch it — it
# propagated out of _get_analyzer(), through DataSource._detect_and_mask_pii(),
# and killed the whole ASGI process (every tenant, not just the uploader).

class _ExplodingNlpProvider:
    """Stands in for NlpEngineProvider whose model download fails."""

    def __init__(self, nlp_configuration=None, *args, **kwargs):
        self.nlp_configuration = nlp_configuration

    def create_engine(self):
        raise SystemExit(1)


class _WorkingNlpProvider:
    """Stands in for a NlpEngineProvider that loads the model successfully."""

    def __init__(self, nlp_configuration=None, *args, **kwargs):
        self.nlp_configuration = nlp_configuration

    def create_engine(self):
        return {"engine": "fake"}


def test_get_analyzer_returns_none_on_systemexit(monkeypatch):
    """A failed spaCy model download must disable PII NER, not kill the process."""
    import pii_masker

    monkeypatch.setattr(pii_masker, "_analyzer", None)
    monkeypatch.setattr(pii_masker, "PRESIDIO_AVAILABLE", True)
    monkeypatch.setattr(pii_masker, "NlpEngineProvider", _ExplodingNlpProvider)
    monkeypatch.setattr(pii_masker, "AnalyzerEngine", lambda **kwargs: object())

    # Must return None (graceful degradation) and must NOT raise SystemExit.
    assert pii_masker._get_analyzer() is None


def test_get_analyzer_returns_none_on_generic_error(monkeypatch):
    """Any other init failure is also non-fatal."""
    import pii_masker

    class _Boom(_ExplodingNlpProvider):
        def create_engine(self):
            raise RuntimeError("no model")

    monkeypatch.setattr(pii_masker, "_analyzer", None)
    monkeypatch.setattr(pii_masker, "PRESIDIO_AVAILABLE", True)
    monkeypatch.setattr(pii_masker, "NlpEngineProvider", _Boom)
    monkeypatch.setattr(pii_masker, "AnalyzerEngine", lambda **kwargs: object())

    assert pii_masker._get_analyzer() is None


def test_get_analyzer_still_returns_engine_on_success(monkeypatch):
    """The added SystemExit handling must not swallow a successful init."""
    import pii_masker

    sentinel = object()
    monkeypatch.setattr(pii_masker, "_analyzer", None)
    monkeypatch.setattr(pii_masker, "PRESIDIO_AVAILABLE", True)
    monkeypatch.setattr(pii_masker, "NlpEngineProvider", _WorkingNlpProvider)
    monkeypatch.setattr(
        pii_masker, "AnalyzerEngine", lambda **kwargs: sentinel
    )

    assert pii_masker._get_analyzer() is sentinel
    # Cached for subsequent callers.
    assert pii_masker._get_analyzer() is sentinel


def test_get_analyzer_not_called_when_presidio_missing(monkeypatch):
    """Without Presidio installed, init is skipped entirely."""
    import pii_masker

    monkeypatch.setattr(pii_masker, "_analyzer", None)
    monkeypatch.setattr(pii_masker, "PRESIDIO_AVAILABLE", False)

    assert pii_masker._get_analyzer() is None