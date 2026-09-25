"""Build the example's DuckDB database, with defects planted on purpose.

    uv run python examples/retail/build.py

Timestamps are written relative to now, in UTC, so freshness checks give
the same answer whenever the example is built. Each defect is named in a
comment next to the row that causes it; the checks under checks/ catch them.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

HERE = Path(__file__).parent


def build(path: Path = HERE / "retail.duckdb") -> Path:
    path.unlink(missing_ok=True)
    now = datetime.now(UTC).replace(tzinfo=None)
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE SCHEMA sales")
        con.execute("CREATE SCHEMA inventory")
        con.execute(
            """CREATE TABLE sales.customers (
                customer_id INTEGER, email VARCHAR, country VARCHAR, signed_up_at TIMESTAMP)"""
        )
        con.executemany(
            "INSERT INTO sales.customers VALUES (?, ?, ?, ?)",
            [
                (1, "ana@example.com", "SG", now - timedelta(days=30)),
                (2, "ben@example.com", "MY", now - timedelta(days=20)),
                (3, "N/A", "SG", now - timedelta(days=10)),  # defect: placeholder email
                (
                    4,
                    "dee@example.com",
                    "XX",
                    now - timedelta(days=5),
                ),  # defect: bad country
                (5, "eve@example.com", "ID", now - timedelta(days=1)),
            ],
        )
        con.execute(
            """CREATE TABLE sales.orders (
                order_id INTEGER, customer_id INTEGER, status VARCHAR,
                amount DECIMAL(10, 2), created_at TIMESTAMP)"""
        )
        con.executemany(
            "INSERT INTO sales.orders VALUES (?, ?, ?, ?, ?)",
            [
                (1001, 1, "shipped", 120.00, now - timedelta(hours=1)),
                (1002, 2, "delivered", 80.50, now - timedelta(hours=2)),
                (
                    1003,
                    None,
                    "pending",
                    45.00,
                    now - timedelta(hours=3),
                ),  # defect: no customer
                (
                    1004,
                    3,
                    "lost",
                    60.00,
                    now - timedelta(hours=4),
                ),  # defect: invalid status
                (
                    1004,
                    3,
                    "pending",
                    60.00,
                    now - timedelta(hours=4),
                ),  # defect: duplicate id
                (
                    1005,
                    5,
                    "shipped",
                    -15.00,
                    now - timedelta(hours=5),
                ),  # defect: negative
                (1006, 4, "cancelled", 30.00, now - timedelta(hours=6)),
            ],
        )
        con.execute(
            """CREATE TABLE inventory.products (
                sku VARCHAR, name VARCHAR, price DECIMAL(10, 2), updated_at TIMESTAMP)"""
        )
        con.executemany(
            "INSERT INTO inventory.products VALUES (?, ?, ?, ?)",
            [
                ("SKU-001", "Kettle", 39.90, now - timedelta(days=3)),
                ("SKU-002", "Toaster", 59.90, now - timedelta(days=3)),
                (
                    "SKU-003",
                    "Blender",
                    89.00,
                    now - timedelta(days=3),
                ),  # defect: stale feed
            ],
        )
    finally:
        con.close()
    return path


if __name__ == "__main__":
    built = build(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "retail.duckdb")
    print(f"built {built}")
