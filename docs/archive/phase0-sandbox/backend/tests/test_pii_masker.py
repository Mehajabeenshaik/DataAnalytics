import pandas as pd
from backend.app.pii_masker import PIIMasker, mask_text, mask_dataframe


def test_mask_text_email_and_phone():
    masker = PIIMasker()
    text = "Contact Alice at alice@example.com or 555-123-4567."
    masked = masker.mask_text(text)
    assert "alice@example.com" not in masked
    assert "555-123-4567" not in masked
    assert "[EMAIL_1]" in masked
    assert "[PHONE_1]" in masked


def test_mask_text_distinct_placeholders():
    masker = PIIMasker()
    text1 = "Email john@a.com and bob@b.com"
    masked1 = masker.mask_text(text1)
    assert "[EMAIL_1]" in masked1
    assert "[EMAIL_2]" in masked1


def test_mask_dataframe():
    df = pd.DataFrame(
        {
            "name": ["John Doe", "Jane Smith"],
            "email": ["john@example.com", "jane@example.com"],
            "revenue": [100, 200],
        }
    )
    masked_df = mask_dataframe(df)
    assert masked_df["revenue"].tolist() == [100, 200]
    assert "john@example.com" not in masked_df["email"].values
    assert "[EMAIL_1]" in masked_df["email"].values[0]
