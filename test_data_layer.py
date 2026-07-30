from data_layer import init_db, query_enriched

init_db()
df = query_enriched()

print("First 5 rows:")
print(df.head(5).to_string())
print(f"\nShape: {df.shape}")
print(f"\nColumns: {list(df.columns)}")

completed = df[df["order_status"] == "completed"]
revenue_by_region = completed.groupby("customer_region")["line_total"].sum().sort_values(ascending=False)
print(f"\nRevenue by region:")
print(revenue_by_region)

revenue_by_category = completed.groupby("product_category")["line_total"].sum().sort_values(ascending=False)
print(f"\nRevenue by category:")
print(revenue_by_category)

print(f"\nOrder status distribution:")
print(df.drop_duplicates("order_id")["order_status"].value_counts())
