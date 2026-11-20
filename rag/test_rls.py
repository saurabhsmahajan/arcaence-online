"""Proves the row-level security rules inside the database, with no model and no API.

Each check switches to a database role and sets the claims a login token would carry,
then queries as that user. Everything is rolled back. Run from the rag folder:
    uv run python test_rls.py
"""
import json
import os

import psycopg
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))


def become(conn, role, sub=None):
    """Act as a database role, carrying the claims a signed login token would carry."""
    claims = {"role": role}
    if sub:
        claims["sub"] = str(sub)
    conn.execute(f"set local role {role}")
    conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))


def ids(conn, role, sub, sql):
    become(conn, role, sub)
    try:
        return {r[0] for r in conn.execute(sql).fetchall()}
    finally:
        conn.rollback()


def denied(conn, role, sub, sql):
    become(conn, role, sub)
    try:
        conn.execute(sql)
        return False
    except psycopg.errors.InsufficientPrivilege:
        return True
    finally:
        conn.rollback()


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    users = dict(conn.execute("select customer_id, auth_user_id from customers").fetchall())
    conn.rollback()
    c1, c2 = users["cust_001"], users["cust_002"]
    check("both customers are linked to a login", c1 is not None and c2 is not None)

    inv = "select invoice_id from invoices"
    check("cust_001 sees only their own invoices",
          ids(conn, "authenticated", c1, inv) == {"inv_1001", "inv_1002"})
    check("cust_001 sees only their own orders",
          ids(conn, "authenticated", c1, "select order_id from orders") == {"ord_1001", "ord_1002"})
    check("cust_001 sees only their own customer row",
          ids(conn, "authenticated", c1, "select customer_id from customers") == {"cust_001"})
    check("cust_002 sees only their own invoice",
          ids(conn, "authenticated", c2, inv) == {"inv_2001"})

    check("Q30: cust_001 asking for cust_002's invoice gets nothing",
          ids(conn, "authenticated", c1,
              "select invoice_id from invoices where customer_id = 'cust_002'") == set())
    check("Q30: cust_001 asking for cust_002's invoice by id gets nothing",
          ids(conn, "authenticated", c1,
              "select invoice_id from invoices where invoice_id = 'inv_2001'") == set())

    check("logged in with no matching customer sees nothing",
          ids(conn, "authenticated", "00000000-0000-0000-0000-000000000000", inv) == set())
    check("anon is denied the table outright",
          denied(conn, "anon", None, inv))
    check("a customer cannot change an invoice",
          denied(conn, "authenticated", c1, "update invoices set amount = 0"))
    check("a customer cannot delete an order",
          denied(conn, "authenticated", c1, "delete from orders"))

print("PASS RLS: each customer sees only their own rows; anon and writes are denied")
