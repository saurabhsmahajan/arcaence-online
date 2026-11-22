"""Smoke test: ops_reader can read the three customer tables and nothing else."""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
url = os.environ["OPS_DATABASE_URL"]


def attempt(label, sql, expect_ok):
    # fresh connection each time so one failure cannot poison the next check
    try:
        with psycopg.connect(url) as conn:
            rows = conn.execute(sql).fetchall() if sql.lstrip().lower().startswith("select") else conn.execute(sql)
            outcome = "ok"
            detail = f"{len(rows)} row(s)" if isinstance(rows, list) else ""
    except Exception as e:  # noqa: BLE001
        outcome = "refused"
        detail = type(e).__name__
    verdict = "PASS" if (outcome == "ok") == expect_ok else "FAIL"
    print(f"{verdict}  {label}: {outcome} {detail}")


attempt("select customers", "select customer_id, email from customers", True)
attempt("select orders", "select order_id from orders", True)
attempt("insert customers", "insert into customers (customer_id, display_name) values ('cust_999', 'x')", False)
attempt("update orders", "update orders set downloaded = true", False)
attempt("select clause_registry", "select * from clause_registry", False)
