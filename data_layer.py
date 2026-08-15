"""
data_layer.py — deterministic, idempotent reseed of ecommerce.db (+ encrypted twin).

Public API:
    init_db(db_path: str | None = None) -> dict
"""

from __future__ import annotations

import random
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import BASE_DIR, DB_PATH


# ---------------------------------------------------------------------------
# Schema (must match the live ecommerce.db)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    customer_id   INTEGER PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         TEXT NOT NULL,
    phone         TEXT,
    city          TEXT,
    state         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id    INTEGER PRIMARY KEY,
    sku           TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    unit_price    REAL NOT NULL,
    stock_qty     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date    TEXT NOT NULL,
    status        TEXT NOT NULL,
    total_amount  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id       INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,
    line_total    REAL NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Deterministic seed data (PRNG seed = 42)
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Casey", "Morgan", "Riley", "Quinn", "Avery",
    "Jamie", "Cameron", "Drew", "Blake", "Skyler", "Reese", "Parker", "Hayden",
    "Rowan", "Sage", "Finley", "Emerson", "Kai", "Logan", "Harper", "Peyton",
    "Charlie", "Dakota", "Phoenix", "River", "Skylar", "Remy",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson",
]

CITIES = [
    ("Austin", "TX"), ("Seattle", "WA"), ("Denver", "CO"), ("Boston", "MA"),
    ("Chicago", "IL"), ("Atlanta", "GA"), ("Portland", "OR"), ("Miami", "FL"),
    ("Phoenix", "AZ"), ("Nashville", "TN"), ("Minneapolis", "MN"), ("Raleigh", "NC"),
]

PRODUCTS = [
    ("ELEC-001", "Wireless Mouse", "Electronics", 29.99),
    ("ELEC-002", "USB-C Hub", "Electronics", 49.99),
    ("ELEC-003", "Noise-Cancel Headphones", "Electronics", 129.99),
    ("ELEC-004", "Mechanical Keyboard", "Electronics", 89.99),
    ("ELEC-005", "4K Webcam", "Electronics", 79.99),
    ("ELEC-006", "Portable SSD 1TB", "Electronics", 109.99),
    ("ELEC-007", "Smart Watch", "Electronics", 199.99),
    ("ELEC-008", "Bluetooth Speaker", "Electronics", 59.99),
    ("ELEC-009", "Laptop Stand", "Electronics", 39.99),
    ("ELEC-010", "USB Microphone", "Electronics", 69.99),
    ("ELEC-011", "Monitor 27in", "Electronics", 249.99),
    ("ELEC-012", "Graphics Tablet", "Electronics", 89.99),
    ("CLTH-001", "Classic T-Shirt", "Clothing", 24.99),
    ("CLTH-002", "Denim Jacket", "Clothing", 79.99),
    ("CLTH-003", "Running Shoes", "Clothing", 99.99),
    ("CLTH-004", "Wool Beanie", "Clothing", 19.99),
    ("CLTH-005", "Cargo Pants", "Clothing", 54.99),
    ("CLTH-006", "Hoodie", "Clothing", 49.99),
    ("CLTH-007", "Athletic Shorts", "Clothing", 29.99),
    ("CLTH-008", "Winter Coat", "Clothing", 149.99),
    ("CLTH-009", "Baseball Cap", "Clothing", 22.99),
    ("CLTH-010", "Socks 3-Pack", "Clothing", 14.99),
    ("CLTH-011", "Dress Shirt", "Clothing", 44.99),
    ("CLTH-012", "Yoga Pants", "Clothing", 39.99),
    ("FURN-001", "Office Chair", "Furniture", 199.99),
    ("FURN-002", "Standing Desk", "Furniture", 349.99),
    ("FURN-003", "Bookshelf", "Furniture", 129.99),
    ("FURN-004", "Desk Lamp", "Furniture", 34.99),
    ("FURN-005", "Filing Cabinet", "Furniture", 89.99),
    ("FURN-006", "Monitor Arm", "Furniture", 59.99),
    ("FURN-007", "Side Table", "Furniture", 79.99),
    ("FURN-008", "Ergo Footrest", "Furniture", 29.99),
    ("FURN-009", "Whiteboard", "Furniture", 49.99),
    ("FURN-010", "Cable Tray", "Furniture", 24.99),
    ("FURN-011", "Desk Organizer", "Furniture", 19.99),
    ("FURN-012", "Task Light", "Furniture", 39.99),
    ("HOME-001", "Ceramic Mug", "Home", 12.99),
    ("HOME-002", "Water Bottle", "Home", 24.99),
    ("HOME-003", "Notebook Set", "Home", 15.99),
    ("HOME-004", "Plant Pot", "Home", 18.99),
    ("HOME-005", "Wall Clock", "Home", 32.99),
    ("HOME-006", "Throw Pillow", "Home", 27.99),
    ("HOME-007", "Candle Set", "Home", 22.99),
    ("HOME-008", "Storage Bin", "Home", 16.99),
    ("HOME-009", "Coaster Set", "Home", 14.99),
    ("HOME-010", "Desk Mat", "Home", 29.99),
    ("HOME-011", "Photo Frame", "Home", 19.99),
    ("HOME-012", "Umbrella", "Home", 25.99),
]

STATUSES = ["completed", "completed", "completed", "pending", "cancelled", "refunded"]


def _generate_customers(rng: random.Random, n: int = 50) -> list[tuple]:
    rows = []
    for i in range(1, n + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        phone = f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
        city, state = rng.choice(CITIES)
        created = (datetime(2023, 1, 1) + timedelta(days=rng.randint(0, 700))).strftime("%Y-%m-%d")
        rows.append((i, first, last, email, phone, city, state, created))
    return rows


def _generate_products() -> list[tuple]:
    rows = []
    for idx, (sku, name, category, price) in enumerate(PRODUCTS, start=1):
        stock = 20 + (idx * 3) % 80
        rows.append((idx, sku, name, category, price, stock))
    return rows


def _generate_orders_and_items(
    rng: random.Random,
    n_customers: int,
    n_products: int,
    n_orders: int = 500,
) -> tuple[list[tuple], list[tuple]]:
    orders = []
    items = []
    item_id = 1
    start = datetime(2024, 1, 1)

    for oid in range(1, n_orders + 1):
        cust_id = rng.randint(1, n_customers)
        days = rng.randint(0, 580)
        order_date = (start + timedelta(days=days)).strftime("%Y-%m-%d")
        status = rng.choice(STATUSES)

        n_lines = rng.randint(1, 3)
        line_total_sum = 0.0
        order_item_rows = []

        for _ in range(n_lines):
            prod_id = rng.randint(1, n_products)
            qty = rng.randint(1, 4)
            # look up unit price from PRODUCTS list (1-based)
            unit_price = PRODUCTS[prod_id - 1][3]
            line_total = round(unit_price * qty, 2)
            line_total_sum += line_total
            order_item_rows.append((item_id, oid, prod_id, qty, unit_price, line_total))
            item_id += 1

        orders.append((oid, cust_id, order_date, status, round(line_total_sum, 2)))
        items.extend(order_item_rows)

    return orders, items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db(db_path: str | None = None) -> dict[str, Any]:
    """
    Rebuild ecommerce.db (and its encrypted twin) with deterministic sample data.

    Returns a summary dict suitable for the /admin/reseed response.
    """
    target = Path(db_path) if db_path else Path(DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 1. Backup existing DB (if present)
    backup_path = None
    if target.exists():
        backup_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup_path)

    # 2. Create fresh DB
    if target.exists():
        target.unlink()

    conn = sqlite3.connect(str(target))
    try:
        conn.executescript(SCHEMA_SQL)

        rng = random.Random(42)  # deterministic

        customers = _generate_customers(rng, n=50)
        products = _generate_products()
        orders, order_items = _generate_orders_and_items(
            rng, n_customers=50, n_products=len(products), n_orders=500
        )

        conn.executemany(
            "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)", customers
        )
        conn.executemany(
            "INSERT INTO products VALUES (?,?,?,?,?,?)", products
        )
        conn.executemany(
            "INSERT INTO orders VALUES (?,?,?,?,?)", orders
        )
        conn.executemany(
            "INSERT INTO order_items VALUES (?,?,?,?,?,?)", order_items
        )
        conn.commit()
    finally:
        conn.close()

    # 3. Re-encrypt if encryption helpers are available
    enc_path = None
    try:
        from encryption import EncryptedDB
        enc_db = EncryptedDB(encrypted_path=str(target) + ".enc")
        enc_path = enc_db.encrypt_existing(str(target))
    except Exception:
        # Encryption is optional; do not fail the reseed
        pass

    summary: dict[str, Any] = {
        "rows_inserted": {
            "customers": len(customers),
            "products": len(products),
            "orders": len(orders),
            "order_items": len(order_items),
        },
        "backup": str(backup_path) if backup_path else None,
        "db_path": str(target),
        "encrypted_path": enc_path,
        "note": (
            "In-memory DataSource sessions still hold old data — "
            "restart the server after reseed."
        ),
    }
    return summary


if __name__ == "__main__":
    result = init_db()
    print(result)
