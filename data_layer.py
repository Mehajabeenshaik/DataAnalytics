import sqlite3
import random
import datetime
from pathlib import Path
import pandas as pd
from config import DB_PATH

random.seed(42)

# ── Column Descriptions ─────────────────────────────────────────────────
# Human-readable descriptions for every column in orders_enriched.
# The LLM reads these to understand what each column means, which
# measurably improves metric selection on ambiguous user questions.

COLUMN_DESCRIPTIONS = {
    "order_id":            "Unique identifier for each order",
    "order_date":          "Date when the order was placed (YYYY-MM-DD)",
    "order_month":         "Month extracted from order_date (YYYY-MM format), useful for monthly aggregations",
    "order_year":          "Year extracted from order_date, useful for year-over-year comparisons",
    "order_status":        "Current status of the order: completed, cancelled, returned, or pending",
    "payment_method":      "How the customer paid: credit_card, debit_card, upi, net_banking, or cod",
    "customer_id":         "Unique identifier for the customer who placed the order",
    "customer_name":       "Full name of the customer (first + last)",
    "customer_email":      "Customer email address (masked for privacy)",
    "customer_phone":      "Customer phone number (masked for privacy)",
    "customer_address":    "Customer street address (masked for privacy)",
    "customer_region":     "Geographic region of the customer: North, South, East, or West",
    "customer_city":       "City where the customer is located",
    "customer_signup_date":"Date when the customer first registered on the platform",
    "product_id":          "Unique identifier for the product",
    "product_name":        "Display name of the product",
    "product_category":    "Top-level product category: Electronics, Clothing, Home & Kitchen, Books, or Sports",
    "product_subcategory": "More specific product grouping within the category",
    "quantity":            "Number of units of this product in this line item",
    "unit_price":          "Price per unit at the time of purchase (may differ from current catalog price)",
    "discount_pct":        "Discount percentage applied to this line item (0.0 to 0.30)",
    "line_total":          "Revenue from this line item: quantity * unit_price * (1 - discount_pct)",
    "cost_price":          "Cost to the business per unit of this product",
    "line_cost":           "Total cost for this line item: quantity * cost_price",
    "line_profit":         "Profit from this line item: line_total - line_cost",
}


# ── Raw Schema ───────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id   INTEGER PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         TEXT NOT NULL,
    phone         TEXT NOT NULL,
    address       TEXT NOT NULL,
    region        TEXT NOT NULL,
    city          TEXT NOT NULL,
    signup_date   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id    INTEGER PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL,
    subcategory   TEXT NOT NULL,
    unit_price    REAL NOT NULL,
    cost_price    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id       INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date     TEXT NOT NULL,
    status         TEXT NOT NULL,
    payment_method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(order_id),
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    quantity    INTEGER NOT NULL,
    unit_price  REAL NOT NULL,
    discount_pct REAL NOT NULL DEFAULT 0.0
);
"""


# ── Denormalized View ────────────────────────────────────────────────────

VIEW_SQL = """
CREATE VIEW IF NOT EXISTS orders_enriched AS
SELECT
    o.order_id,
    o.order_date,
    strftime('%Y-%m', o.order_date)                           AS order_month,
    CAST(strftime('%Y', o.order_date) AS INTEGER)             AS order_year,
    o.status                                                  AS order_status,
    o.payment_method,

    c.customer_id,
    c.first_name || ' ' || c.last_name                       AS customer_name,
    c.email                                                   AS customer_email,
    c.phone                                                   AS customer_phone,
    c.address                                                 AS customer_address,
    c.region                                                  AS customer_region,
    c.city                                                    AS customer_city,
    c.signup_date                                              AS customer_signup_date,

    p.product_id,
    p.product_name,
    p.category                                                AS product_category,
    p.subcategory                                             AS product_subcategory,

    oi.quantity,
    oi.unit_price,
    oi.discount_pct,
    ROUND(oi.quantity * oi.unit_price * (1.0 - oi.discount_pct), 2)  AS line_total,
    p.cost_price,
    ROUND(oi.quantity * p.cost_price, 2)                      AS line_cost,
    ROUND(oi.quantity * oi.unit_price * (1.0 - oi.discount_pct)
        - oi.quantity * p.cost_price, 2)                      AS line_profit
FROM order_items oi
JOIN orders   o ON oi.order_id   = o.order_id
JOIN products p ON oi.product_id = p.product_id
JOIN customers c ON o.customer_id = c.customer_id;
"""


# ── Seed Data ────────────────────────────────────────────────────────────

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh",
    "Ayaan", "Krishna", "Ishaan", "Ananya", "Diya", "Myra", "Sara",
    "Anika", "Aadhya", "Isha", "Riya", "Priya", "Neha", "Rahul",
    "Amit", "Pooja", "Sneha", "Kiran", "Vikram", "Deepak", "Meera",
    "Rohan", "Kavya", "Nikhil", "Tanvi", "Harsh", "Shruti", "Manish",
    "Ritika", "Gaurav", "Pallavi", "Suresh", "Divya",
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Gupta", "Singh", "Kumar", "Joshi",
    "Reddy", "Nair", "Iyer", "Das", "Mehta", "Shah", "Rao", "Mishra",
    "Chauhan", "Pandey", "Chopra", "Bhat", "Kulkarni", "Menon",
    "Pillai", "Deshmukh", "Patil", "Saxena",
]

REGIONS_CITIES = {
    "North": ["Delhi", "Jaipur", "Lucknow", "Chandigarh", "Amritsar"],
    "South": ["Bangalore", "Chennai", "Hyderabad", "Kochi", "Coimbatore"],
    "East":  ["Kolkata", "Bhubaneswar", "Patna", "Guwahati", "Ranchi"],
    "West":  ["Mumbai", "Pune", "Ahmedabad", "Surat", "Nagpur"],
}

STREETS = [
    "MG Road", "Brigade Road", "Park Street", "Connaught Place",
    "FC Road", "Marine Drive", "Anna Nagar", "Banjara Hills",
    "Salt Lake Sector V", "Koramangala 4th Block", "Aundh Road",
    "Jubilee Hills Road No 36", "Residency Road", "Linking Road",
    "Nehru Place", "Rajpath", "Carter Road", "Indiranagar 12th Main",
    "Hitech City Road", "EM Bypass",
]

PRODUCTS_CATALOG = {
    "Electronics": {
        "Smartphones":   [("iPhone 15", 79999, 62000), ("Galaxy S24", 69999, 54000),
                          ("Pixel 8", 52999, 41000), ("OnePlus 12", 49999, 38000)],
        "Laptops":       [("MacBook Air M3", 114900, 89000), ("ThinkPad X1", 89999, 70000),
                          ("HP Pavilion 15", 54999, 42000), ("Dell Inspiron", 49999, 38000)],
        "Accessories":   [("AirPods Pro", 24999, 18000), ("Sony WH-1000XM5", 29999, 22000),
                          ("Logitech MX Master", 8999, 6500), ("Samsung T7 SSD", 7499, 5500)],
    },
    "Clothing": {
        "Men's Wear":    [("Levi's 501 Jeans", 3499, 1800), ("Nike Dri-Fit Tee", 1999, 900),
                          ("Allen Solly Shirt", 1499, 700), ("Woodland Jacket", 4999, 2800)],
        "Women's Wear":  [("Zara Midi Dress", 3999, 2000), ("H&M Blazer", 2999, 1500),
                          ("FabIndia Kurti", 1299, 600), ("Biba Palazzo Set", 1799, 850)],
        "Footwear":      [("Nike Air Max 90", 8999, 5200), ("Adidas Ultraboost", 12999, 7800),
                          ("Bata Formal Shoes", 2499, 1200), ("Crocs Classic", 2999, 1400)],
    },
    "Home & Kitchen": {
        "Appliances":    [("Instant Pot Duo", 8999, 5500), ("Dyson V15 Vacuum", 52999, 38000),
                          ("Philips Air Fryer", 7999, 4800), ("Bosch Mixer Grinder", 4999, 2900)],
        "Furniture":     [("IKEA Standing Desk", 15999, 9500), ("Nilkamal Office Chair", 8999, 5200),
                          ("HomeTown Bookshelf", 6999, 4000), ("Wakefit Mattress", 12999, 7500)],
    },
    "Books": {
        "Fiction":       [("Atomic Habits", 499, 180), ("The Alchemist", 350, 120),
                          ("Sapiens", 599, 220), ("Ikigai", 399, 150)],
        "Technical":     [("CLRS Algorithms", 899, 400), ("Python Crash Course", 699, 300),
                          ("Deep Learning (Goodfellow)", 1299, 600), ("System Design Interview", 799, 350)],
    },
    "Sports": {
        "Fitness":       [("Yoga Mat (Liforme)", 2999, 1500), ("Resistance Bands Set", 999, 400),
                          ("Fitbit Charge 6", 12999, 8500), ("Dumbbell Set 20kg", 3499, 1800)],
        "Outdoor":       [("Wildcraft Trekking Bag", 2499, 1200), ("Quechua Tent 3P", 5999, 3200),
                          ("Decathlon Cycling Helmet", 1499, 700), ("Coleman Sleeping Bag", 3999, 2000)],
    },
}

STATUSES = ["completed"] * 75 + ["pending"] * 10 + ["cancelled"] * 10 + ["returned"] * 5
PAYMENT_METHODS = ["credit_card", "debit_card", "upi", "net_banking", "cod"]


def _generate_customers(n=250):
    customers = []
    start = datetime.date(2022, 1, 1)
    end = datetime.date(2025, 12, 31)
    span = (end - start).days
    email_domains = ["gmail.com", "yahoo.co.in", "outlook.com", "hotmail.com", "rediffmail.com"]
    for i in range(1, n + 1):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        region = random.choice(list(REGIONS_CITIES.keys()))
        city = random.choice(REGIONS_CITIES[region])
        signup = start + datetime.timedelta(days=random.randint(0, span))
        email = f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@{random.choice(email_domains)}"
        phone = f"+91-{random.randint(70000, 99999)}-{random.randint(10000, 99999)}"
        address = f"{random.randint(1, 500)}, {random.choice(STREETS)}, {city}"
        customers.append((
            i, first, last, email, phone, address, region, city, signup.isoformat(),
        ))
    return customers


def _generate_products():
    products = []
    pid = 1
    for category, subcats in PRODUCTS_CATALOG.items():
        for subcat, items in subcats.items():
            for name, price, cost in items:
                products.append((pid, name, category, subcat, price, cost))
                pid += 1
    return products


def _generate_orders_and_items(n_orders=2500, products=None, n_customers=250):
    orders = []
    items = []
    start = datetime.date(2023, 1, 1)
    end = datetime.date(2026, 6, 30)
    span = (end - start).days
    discounts = [0.0] * 60 + [0.05] * 15 + [0.10] * 12 + [0.15] * 8 + [0.20] * 4 + [0.30] * 1

    for oid in range(1, n_orders + 1):
        cid = random.randint(1, n_customers)
        odate = start + datetime.timedelta(days=random.randint(0, span))
        status = random.choice(STATUSES)
        payment = random.choice(PAYMENT_METHODS)
        orders.append((oid, cid, odate.isoformat(), status, payment))

        n_items = random.choices([1, 2, 3, 4, 5], weights=[40, 30, 15, 10, 5])[0]
        chosen = random.sample(products, min(n_items, len(products)))
        for prod in chosen:
            qty = random.choices([1, 2, 3, 4, 5], weights=[50, 25, 15, 7, 3])[0]
            disc = random.choice(discounts)
            items.append((oid, prod[0], qty, prod[4], disc))

    return orders, items


# ── Public API ───────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH, force_reseed: bool = False) -> str:
    """Create schema, seed data with PII masking, and build the orders_enriched view.
    Returns the path to the database file.
    """
    path = Path(db_path)

    if path.exists() and not force_reseed:
        conn = sqlite3.connect(db_path)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(customers)").fetchall()]
            if cols and "phone" not in cols:
                force_reseed = True
                print("Schema migration detected, reseeding with phone/address columns...")
        except sqlite3.OperationalError:
            force_reseed = True
        finally:
            conn.close()

    if force_reseed and path.exists():
        path.unlink()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)

    row_count = cur.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    if row_count == 0:
        from pii_masker import PIIMasker
        masker = PIIMasker()
        masker.clear_vault()

        customers_raw = _generate_customers()
        customers, pii_detections = masker.mask_customers_batch(customers_raw)
        products = _generate_products()
        orders, items = _generate_orders_and_items(products=products)

        cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)", customers)
        cur.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)
        cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", orders)
        cur.executemany("INSERT INTO order_items (order_id,product_id,quantity,unit_price,discount_pct) VALUES (?,?,?,?,?)", items)

        print(f"Seeded: {len(customers)} customers, {len(products)} products, "
              f"{len(orders)} orders, {len(items)} line items")
        print(f"PII: Presidio scanned and masked {len(customers)} customer records ({pii_detections} entities detected)")

    cur.execute("DROP VIEW IF EXISTS orders_enriched")
    cur.executescript(VIEW_SQL)
    conn.commit()
    conn.close()

    return db_path


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ── Filter allowlist ────────────────────────────────────────────────────
# Only these columns may appear in a WHERE clause built by resolve_filter().
# Any column not listed here raises ValueError — an LLM cannot inject an
# arbitrary column name and pivot to a destructive statement.
_ALLOWED_FILTER_COLUMNS: frozenset[str] = frozenset({
    "order_status",
    "payment_method",
    "customer_region",
    "order_year",
    "order_month",
    "product_category",
    "product_subcategory",
    "order_date",
})

# Allowed SQL comparison operators.  Values are ALWAYS bound via parameterized
# placeholders — never interpolated into the SQL string.
_ALLOWED_OPERATORS: frozenset[str] = frozenset({"=", "!=", ">", "<", ">=", "<="})


def resolve_filter(filters: dict, db_path: str = DB_PATH) -> tuple[str, list]:
    """Build a safe, parameterized WHERE clause from a validated filter dict.

    Parameters
    ----------
    filters:
        A dict mapping column names to filter specifications.  Each value is
        either:

        * A scalar  — treated as an equality check  (``column = ?``).
        * A 2-tuple ``(operator, value)``  — e.g. ``(">", 2024)``.
        * A list / tuple of scalars — treated as an IN clause
          ``column IN (?, ?, …)``.
        * A dict ``{"BETWEEN": (lo, hi)}`` — treated as
          ``column BETWEEN ? AND ?``.

    Returns
    -------
    (where_clause, params)
        *where_clause* is a string like ``"order_status = ? AND order_year > ?"``
        (empty string if *filters* is empty).
        *params* is the list of values to bind.

    Raises
    ------
    ValueError
        If any column name is not in ``_ALLOWED_FILTER_COLUMNS``.
    ValueError
        If an operator is not in ``_ALLOWED_OPERATORS``.
    """
    clauses: list[str] = []
    params: list = []

    for column, spec in filters.items():
        if column not in _ALLOWED_FILTER_COLUMNS:
            raise ValueError(
                f"Column '{column}' is not in the filter allowlist. "
                f"Allowed columns: {sorted(_ALLOWED_FILTER_COLUMNS)}"
            )

        if isinstance(spec, dict) and "BETWEEN" in spec:
            # {"BETWEEN": (lo, hi)}
            lo, hi = spec["BETWEEN"]
            clauses.append(f"{column} BETWEEN ? AND ?")
            params.extend([lo, hi])

        elif isinstance(spec, (list, tuple)) and not (
            len(spec) == 2 and isinstance(spec[0], str) and spec[0] in _ALLOWED_OPERATORS
        ):
            # List of scalars → IN clause
            placeholders = ",".join(["?"] * len(spec))
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(spec)

        elif isinstance(spec, (list, tuple)) and len(spec) == 2 and isinstance(spec[0], str):
            # (operator, value) pair
            operator, value = spec
            if operator not in _ALLOWED_OPERATORS:
                raise ValueError(
                    f"Operator '{operator}' is not allowed. "
                    f"Allowed operators: {sorted(_ALLOWED_OPERATORS)}"
                )
            clauses.append(f"{column} {operator} ?")
            params.append(value)

        else:
            # Scalar → equality
            clauses.append(f"{column} = ?")
            params.append(spec)

    where_clause = " AND ".join(clauses)
    return where_clause, params


def query_enriched(filters: dict | None = None,
                   db_path: str = DB_PATH) -> pd.DataFrame:
    """Return a DataFrame from orders_enriched, optionally filtered.

    Parameters
    ----------
    filters:
        Optional dict passed to :func:`resolve_filter`.  Only columns in the
        allowlist are accepted; anything else raises ``ValueError``.
        Pass ``None`` (default) or an empty dict to return all rows.
    db_path:
        Path to the SQLite database.

    Notes
    -----
    The previous ``sql_where: str`` parameter has been **removed**.  Accepting
    a raw SQL fragment from callers (especially LLM output) is a SQL-injection
    risk.  All filter conditions must go through :func:`resolve_filter` which
    validates column names against an allowlist and binds values as
    parameterized placeholders — the SQL text never contains a user-supplied
    value.
    """
    base = "SELECT * FROM orders_enriched"
    params: list = []

    if filters:
        where_clause, params = resolve_filter(filters, db_path=db_path)
        if where_clause:
            base = f"{base} WHERE {where_clause}"

    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(base, conn, params=params)
    conn.close()
    return df


def get_column_descriptions() -> dict[str, str]:
    return COLUMN_DESCRIPTIONS.copy()


def print_summary(db_path: str = DB_PATH):
    """Print a quick summary of the database contents."""
    conn = sqlite3.connect(db_path)
    tables = ["customers", "products", "orders", "order_items"]
    print("\n-- Database Summary --")
    for t in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:15s} -> {count:,} rows")

    enriched_count = conn.execute("SELECT COUNT(*) FROM orders_enriched").fetchone()[0]
    print(f"  {'orders_enriched':15s} -> {enriched_count:,} rows (view)")

    rev = conn.execute("SELECT ROUND(SUM(line_total),2) FROM orders_enriched WHERE order_status='completed'").fetchone()[0]
    print(f"\n  Total completed revenue: Rs {rev:,.2f}")

    print("\n-- Column Descriptions --")
    for col, desc in COLUMN_DESCRIPTIONS.items():
        print(f"  {col:25s} | {desc}")

    conn.close()


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    db = init_db(force_reseed=force)
    print(f"\nDatabase ready at: {db}")
    print_summary(db)
