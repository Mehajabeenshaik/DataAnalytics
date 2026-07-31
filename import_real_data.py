"""import_real_data.py — Import Olist Brazilian E-Commerce dataset.

Downloads the Olist dataset from Kaggle (via kagglehub), maps its columns
to the existing schema (customers, products, orders, order_items), and
inserts the data into ecommerce.db.

Olist dataset files used:
    - olist_customers_dataset.csv
    - olist_orders_dataset.csv
    - olist_order_items_dataset.csv
    - olist_order_payments_dataset.csv
    - olist_products_dataset.csv
    - product_category_name_translation.csv

PII note:
    Olist pre-anonymizes customer identity — there are no real names, emails,
    or phone numbers in this dataset.  PIIMasker's role here is defensive-only,
    not required.  Unlike a real business export (where a customer table
    might contain raw PII that must be masked before storage), this dataset
    arrives already anonymized by Olist.  We generate placeholder values for
    first_name, last_name, email, phone, and address so the existing schema
    (which has NOT NULL constraints on those columns) can accept the rows
    without modification.

Usage:
    python import_real_data.py            # import (replaces existing data)
    python import_real_data.py --force     # force re-download + re-import
"""

import os
import sys
import sqlite3
from pathlib import Path
import pandas as pd

from config import DB_PATH
from data_layer import SCHEMA_SQL, VIEW_SQL


# ── Mappings ─────────────────────────────────────────────────────────────

# Brazilian states → existing schema's region (North/South/East/West).
# Brazil has 5 macro-regions; we map them to the 4 values used by the
# existing schema (North, South, East, West):
#   Norte (North)        → North
#   Nordeste (Northeast) → East
#   Sudeste (Southeast)  → South
#   Sul (South)          → South
#   Centro-Oeste (C-West)→ West
BRAZILIAN_STATE_TO_REGION = {
    # Norte → North
    "AC": "North", "AM": "North", "AP": "North", "PA": "North",
    "RO": "North", "RR": "North", "TO": "North",
    # Nordeste → East
    "AL": "East", "BA": "East", "CE": "East", "MA": "East",
    "PB": "East", "PE": "East", "PI": "East", "RN": "East", "SE": "East",
    # Sudeste → South
    "ES": "South", "MG": "South", "RJ": "South", "SP": "South",
    # Sul → South
    "PR": "South", "RS": "South", "SC": "South",
    # Centro-Oeste → West
    "DF": "West", "GO": "West", "MT": "West", "MS": "West",
}

# Olist payment types → existing schema's payment_method.
# Olist has: credit_card, debit_card, boleto, voucher, not_defined
# Schema has: credit_card, debit_card, upi, net_banking, cod
PAYMENT_TYPE_MAP = {
    "credit_card": "credit_card",
    "debit_card": "debit_card",
    "boleto": "net_banking",      # Boleto = Brazilian bank slip → net_banking
    "voucher": "upi",              # Voucher = prepaid/gift card → upi (digital)
    "not_defined": "cod",          # Default fallback → cash on delivery
}

# Olist order statuses → existing schema's status.
# Olist has: delivered, shipped, canceled, processing, approved, unavailable, created, invoiced
# Schema has: completed, pending, cancelled, returned
ORDER_STATUS_MAP = {
    "delivered": "completed",
    "shipped": "pending",
    "canceled": "cancelled",       # note: Olist uses 1 'l', schema uses 2
    "processing": "pending",
    "approved": "pending",
    "unavailable": "cancelled",
    "created": "pending",
    "invoiced": "pending",
}

# Estimated cost as a fraction of price — Olist doesn't provide cost data.
# 0.75 means a 25% profit margin estimate.  This only affects line_cost
# and line_profit in the orders_enriched view; revenue (line_total) is
# always the actual price from the Olist dataset.
COST_PRICE_RATIO = 0.75


# ── Dataset download ─────────────────────────────────────────────────────

def download_olist_dataset() -> Path:
    """Download the Olist dataset via kagglehub and return the path."""
    try:
        import kagglehub
    except ImportError:
        print("ERROR: kagglehub not installed. Run: pip install kagglehub")
        sys.exit(1)

    print("Downloading Olist Brazilian E-Commerce dataset from Kaggle...")
    print("(This may take a few minutes on first run; cached afterwards.)")
    path = kagglehub.dataset_download("olistbr/brazilian-ecommerce")
    path = Path(path)
    print(f"Dataset cached at: {path}")
    return path


# ── CSV loading ──────────────────────────────────────────────────────────

def load_csvs(data_path: Path) -> dict:
    """Load all relevant Olist CSVs into DataFrames."""
    csv_files = {
        "customers": "olist_customers_dataset.csv",
        "orders": "olist_orders_dataset.csv",
        "order_items": "olist_order_items_dataset.csv",
        "order_payments": "olist_order_payments_dataset.csv",
        "products": "olist_products_dataset.csv",
        "category_translation": "product_category_name_translation.csv",
    }

    data = {}
    for key, filename in csv_files.items():
        filepath = data_path / filename
        if not filepath.exists():
            print(f"  WARNING: {filename} not found at {filepath}")
            data[key] = pd.DataFrame()
        else:
            data[key] = pd.read_csv(filepath)
            print(f"  Loaded {filename}: {len(data[key]):,} rows")

    return data


# ── Transform functions ──────────────────────────────────────────────────

def transform_customers(
    customers_df: pd.DataFrame,
    orders_df: pd.DataFrame,
) -> tuple[list[tuple], dict[str, int], int]:
    """Transform Olist customers to match the existing schema.

    Olist pre-anonymizes customer identity — no names, emails, or phones.
    We generate placeholder values for these NOT NULL columns.

    Returns (rows, id_map, skipped_count).
    """
    if customers_df.empty:
        return [], {}, 0

    # Build customer_id mapping (Olist string → sequential int)
    olist_ids = customers_df["customer_id"].unique()
    id_map = {oid: i + 1 for i, oid in enumerate(olist_ids)}

    # Find each customer's earliest order date for signup_date
    if not orders_df.empty:
        orders_df["order_date"] = pd.to_datetime(
            orders_df["order_purchase_timestamp"]
        ).dt.date
        first_order = (
            orders_df.groupby("customer_id")["order_date"]
            .min()
            .to_dict()
        )
    else:
        first_order = {}

    rows = []
    skipped = 0

    for _, row in customers_df.iterrows():
        olist_id = row["customer_id"]
        int_id = id_map[olist_id]

        city = str(row.get("customer_city", "Unknown"))
        state = str(row.get("customer_state", "")).upper()
        region = BRAZILIAN_STATE_TO_REGION.get(state, "West")
        zip_prefix = row.get("customer_zip_code_prefix", "00000")

        # Placeholder identity fields — Olist already anonymized these.
        # PIIMasker is NOT needed here (defensive-only, noted in module docstring).
        first_name = "Customer"
        last_name = f"{int_id:05d}"
        email = f"customer.{int_id:05d}@olist.anon"
        phone = f"+55-XXXXX-{int_id:05d}"
        address = f"CEP {zip_prefix:05d}, {city}"

        # signup_date: use earliest order date, or a default
        signup = first_order.get(olist_id)
        if signup is not None:
            signup_date = signup.isoformat()
        else:
            signup_date = "2016-01-01"  # default if no orders found

        rows.append((
            int_id, first_name, last_name, email, phone,
            address, region, city, signup_date,
        ))

    return rows, id_map, skipped


def transform_products(
    products_df: pd.DataFrame,
    category_translation_df: pd.DataFrame,
    order_items_df: pd.DataFrame,
) -> tuple[list[tuple], dict[str, int], int]:
    """Transform Olist products to match the existing schema.

    Olist doesn't have product names or cost prices.  We:
    - Use "Product {id}" as the name (placeholder)
    - Translate product_category_name from Portuguese to English
    - Use "General" as subcategory (Olist doesn't have subcategories)
    - Calculate unit_price as the average price from order_items
    - Estimate cost_price as COST_PRICE_RATIO * unit_price

    Returns (rows, id_map, skipped_count).
    """
    if products_df.empty:
        return [], {}, 0

    # Build product_id mapping (Olist string → sequential int)
    olist_ids = products_df["product_id"].unique()
    id_map = {oid: i + 1 for i, oid in enumerate(olist_ids)}

    # Build translation dict: Portuguese → English
    if not category_translation_df.empty:
        translation = dict(zip(
            category_translation_df["product_category_name"],
            category_translation_df["product_category_name_english"],
        ))
    else:
        translation = {}

    # Calculate average price per product from order_items
    if not order_items_df.empty:
        avg_price = (
            order_items_df.groupby("product_id")["price"]
            .mean()
            .to_dict()
        )
    else:
        avg_price = {}

    rows = []
    skipped = 0

    for _, row in products_df.iterrows():
        olist_id = row["product_id"]
        int_id = id_map[olist_id]

        # Translate category from Portuguese to English
        pt_category = row.get("product_category_name")
        if pd.isna(pt_category) or not pt_category:
            category = "Unknown"
        else:
            category = translation.get(pt_category, pt_category)

        # Placeholder product name (Olist doesn't have product names)
        product_name = f"Product {int_id:05d}"

        # Average price from order_items, or 0 if no orders
        unit_price = avg_price.get(olist_id, 0.0)
        if pd.isna(unit_price):
            unit_price = 0.0

        # Estimated cost price (Olist doesn't provide cost data)
        cost_price = round(unit_price * COST_PRICE_RATIO, 2)

        rows.append((
            int_id, product_name, category, "General",
            unit_price, cost_price,
        ))

    return rows, id_map, skipped


def transform_orders(
    orders_df: pd.DataFrame,
    payments_df: pd.DataFrame,
    customer_id_map: dict[str, int],
) -> tuple[list[tuple], dict[str, int], int]:
    """Transform Olist orders to match the existing schema.

    Returns (rows, id_map, skipped_count).
    """
    if orders_df.empty:
        return [], {}, 0

    # Build order_id mapping (Olist string → sequential int)
    olist_ids = orders_df["order_id"].unique()
    id_map = {oid: i + 1 for i, oid in enumerate(olist_ids)}

    # Pick one payment_method per order: the payment with the largest
    # payment_value.  This is a simplification — a single Olist order can
    # have multiple payment rows (e.g., part credit_card, part voucher).
    # We pick the largest because it represents the "primary" payment method.
    if not payments_df.empty:
        # Sort by payment_value descending, then take first per order_id
        primary_payment = (
            payments_df.sort_values("payment_value", ascending=False)
            .drop_duplicates("order_id", keep="first")
            .set_index("order_id")["payment_type"]
            .to_dict()
        )
    else:
        primary_payment = {}

    rows = []
    skipped = 0

    for _, row in orders_df.iterrows():
        olist_id = row["order_id"]
        int_id = id_map[olist_id]

        olist_customer_id = row["customer_id"]
        if olist_customer_id not in customer_id_map:
            skipped += 1
            continue

        customer_id = customer_id_map[olist_customer_id]

        # Extract date from order_purchase_timestamp
        try:
            order_date = pd.to_datetime(
                row["order_purchase_timestamp"]
            ).date().isoformat()
        except (ValueError, TypeError):
            skipped += 1
            continue

        # Map order status
        olist_status = str(row.get("order_status", "")).lower()
        status = ORDER_STATUS_MAP.get(olist_status, "pending")

        # Get payment method
        payment_type = primary_payment.get(olist_id, "not_defined")
        payment_method = PAYMENT_TYPE_MAP.get(payment_type, "cod")

        rows.append((
            int_id, customer_id, order_date, status, payment_method,
        ))

    return rows, id_map, skipped


def transform_order_items(
    order_items_df: pd.DataFrame,
    order_id_map: dict[str, int],
    product_id_map: dict[str, int],
) -> tuple[list[tuple], int]:
    """Transform Olist order_items to match the existing schema.

    Each Olist row is one item with quantity=1.  discount_pct=0 (Olist
    doesn't have discount data).  freight_value is ignored (the existing
    schema doesn't have a shipping cost column).

    Returns (rows, skipped_count).
    """
    if order_items_df.empty:
        return [], 0

    rows = []
    skipped = 0

    for _, row in order_items_df.iterrows():
        olist_order_id = row["order_id"]
        olist_product_id = row["product_id"]

        if olist_order_id not in order_id_map:
            skipped += 1
            continue
        if olist_product_id not in product_id_map:
            skipped += 1
            continue

        order_id = order_id_map[olist_order_id]
        product_id = product_id_map[olist_product_id]
        quantity = 1  # each Olist row = 1 item
        unit_price = float(row["price"])
        discount_pct = 0.0  # Olist doesn't have discount data

        rows.append((
            order_id, product_id, quantity, unit_price, discount_pct,
        ))

    return rows, skipped


# ── Database insertion ────────────────────────────────────────────────────

def import_data(db_path: str = DB_PATH, force_download: bool = False) -> None:
    """Download, transform, and import the Olist dataset into ecommerce.db.

    This replaces all existing data in the database.  The orders_enriched
    view is re-created after insertion.
    """
    # Step 1: Download dataset
    data_path = download_olist_dataset()

    # Step 2: Load CSVs
    print("\n── Loading CSVs ──")
    data = load_csvs(data_path)

    # Step 3: Transform data
    print("\n── Transforming data ──")

    print("  Transforming customers...")
    customer_rows, customer_id_map, cust_skipped = transform_customers(
        data["customers"], data["orders"]
    )
    print(f"    → {len(customer_rows):,} customers ready ({cust_skipped} skipped)")

    print("  Transforming products...")
    product_rows, product_id_map, prod_skipped = transform_products(
        data["products"], data["category_translation"], data["order_items"]
    )
    print(f"    → {len(product_rows):,} products ready ({prod_skipped} skipped)")

    print("  Transforming orders...")
    order_rows, order_id_map, order_skipped = transform_orders(
        data["orders"], data["order_payments"], customer_id_map
    )
    print(f"    → {len(order_rows):,} orders ready ({order_skipped} skipped)")

    print("  Transforming order items...")
    item_rows, item_skipped = transform_order_items(
        data["order_items"], order_id_map, product_id_map
    )
    print(f"    → {len(item_rows):,} order items ready ({item_skipped} skipped)")

    # Step 4: Insert into database
    print(f"\n── Importing into database: {db_path} ──")

    # Remove existing database to start fresh
    db_file = Path(db_path)
    if db_file.exists():
        db_file.unlink()
        print(f"  Removed existing database: {db_path}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create schema
    cur.executescript(SCHEMA_SQL)
    print("  Schema created")

    # Insert data
    if customer_rows:
        cur.executemany(
            "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)",
            customer_rows,
        )
        print(f"  Inserted {len(customer_rows):,} customers")

    if product_rows:
        cur.executemany(
            "INSERT INTO products VALUES (?,?,?,?,?,?)",
            product_rows,
        )
        print(f"  Inserted {len(product_rows):,} products")

    if order_rows:
        cur.executemany(
            "INSERT INTO orders VALUES (?,?,?,?,?)",
            order_rows,
        )
        print(f"  Inserted {len(order_rows):,} orders")

    if item_rows:
        cur.executemany(
            "INSERT INTO order_items (order_id,product_id,quantity,unit_price,discount_pct) "
            "VALUES (?,?,?,?,?)",
            item_rows,
        )
        print(f"  Inserted {len(item_rows):,} order items")

    # Create the orders_enriched view
    cur.execute("DROP VIEW IF EXISTS orders_enriched")
    cur.executescript(VIEW_SQL)
    print("  View orders_enriched created")

    conn.commit()
    conn.close()

    # Step 5: Print summary
    print("\n" + "=" * 60)
    print("  IMPORT SUMMARY")
    print("=" * 60)

    conn = sqlite3.connect(db_path)
    tables = [
        ("customers", "customers"),
        ("products", "products"),
        ("orders", "orders"),
        ("order_items", "order_items"),
    ]
    for label, table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {label:15s} → {count:,} rows")

    enriched_count = conn.execute(
        "SELECT COUNT(*) FROM orders_enriched"
    ).fetchone()[0]
    print(f"  {'orders_enriched':15s} → {enriched_count:,} rows (view)")

    # Revenue summary
    rev = conn.execute(
        "SELECT ROUND(SUM(line_total), 2) FROM orders_enriched "
        "WHERE order_status = 'completed'"
    ).fetchone()[0]
    if rev:
        print(f"\n  Total completed revenue: R$ {rev:,.2f}")
    else:
        print("\n  Total completed revenue: R$ 0.00")

    # Status breakdown
    print("\n  Order status breakdown:")
    status_counts = conn.execute(
        "SELECT order_status, COUNT(DISTINCT order_id) "
        "FROM orders_enriched GROUP BY order_status ORDER BY 2 DESC"
    ).fetchall()
    for status, count in status_counts:
        print(f"    {status:15s} → {count:,} orders")

    # Region breakdown
    print("\n  Region breakdown (completed orders):")
    region_counts = conn.execute(
        "SELECT customer_region, ROUND(SUM(line_total), 2) "
        "FROM orders_enriched WHERE order_status = 'completed' "
        "GROUP BY customer_region ORDER BY 2 DESC"
    ).fetchall()
    for region, revenue in region_counts:
        print(f"    {region:15s} → R$ {revenue:,.2f}")

    # Skipped rows summary
    total_skipped = cust_skipped + prod_skipped + order_skipped + item_skipped
    print(f"\n  Total rows skipped: {total_skipped:,}")
    if total_skipped > 0:
        print(f"    Customers skipped: {cust_skipped}")
        print(f"    Products skipped:   {prod_skipped}")
        print(f"    Orders skipped:     {order_skipped}")
        print(f"    Order items skipped: {item_skipped}")

    conn.close()
    print("\n  ✅ Import complete!")
    print("=" * 60)


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    force = "--force" in sys.argv
    import_data(force_download=force)