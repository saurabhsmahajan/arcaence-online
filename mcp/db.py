"""Read-only data access. Connects with OPS_DATABASE_URL (the ops_reader role) and nothing else."""
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()


def _rows(sql: str, params: tuple) -> list[dict]:
    # One short connection per call. The role is read-only and has a 5s statement timeout.
    with psycopg.connect(os.environ["OPS_DATABASE_URL"], row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


def fetch_account(customer_id: str) -> dict | None:
    rows = _rows(
        "select customer_id, display_name, plan, billing, currency, status, created_at, email, phone "
        "from customers where customer_id = %s",
        (customer_id,),
    )
    return rows[0] if rows else None


def fetch_order(order_id: str) -> dict | None:
    rows = _rows(
        "select o.order_id, o.customer_id, o.item, o.kind, o.amount, o.currency, "
        "o.purchased_at, o.downloaded, i.invoice_id, i.issued_on as invoice_issued_on "
        "from orders o left join invoices i on i.order_id = o.order_id "
        "where o.order_id = %s",
        (order_id,),
    )
    return rows[0] if rows else None


def fetch_subscription_orders(customer_id: str) -> list[dict]:
    return _rows(
        "select order_id, item, amount, currency, purchased_at "
        "from orders where customer_id = %s and kind = 'subscription' "
        "order by purchased_at desc",
        (customer_id,),
    )


def assert_login_role(expected: str) -> None:
    """Refuse to start if the database login is not the role this server was launched as."""
    actual = _rows("select current_user as u", ())[0]["u"]
    if actual != expected:
        raise SystemExit(f"Database login is {actual!r}, expected {expected!r}. Refusing to start.")
