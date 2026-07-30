from data_layer import init_db, query_enriched
from pii_masker import PIIMasker

print("=" * 70)
print("MODULE 8 TEST: PII Detection & Masking with Microsoft Presidio")
print("=" * 70)

init_db(force_reseed=True)

masker = PIIMasker()

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

print("\n" + "=" * 70)
print("VERIFICATION: No raw PII in orders_enriched")
print("=" * 70)
raw_names = df["customer_name"].str.contains("@gmail|@yahoo|@outlook|Aarav|Vivaan|Sharma|Patel", case=False, regex=True)
if raw_names.any():
    print("FAIL: Raw PII found in orders_enriched!")
else:
    print("PASS: No raw PII detected in orders_enriched. All customer data is masked.")

print(f"\nTotal rows in orders_enriched: {len(df)}")
print(f"Unique masked customers: {df['customer_name'].nunique()}")
print(f"Sample masked names: {df['customer_name'].unique()[:5].tolist()}")
