"""The deletion request and cancel actions against the real database. Every run is rolled back.
Run from the mcp folder: uv run python test_privacy_deletion.py"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values, load_dotenv

import db_write
import privacy

load_dotenv()
OWNER = os.environ.get("DATABASE_URL") or dotenv_values(Path(__file__).resolve().parent.parent / "rag" / ".env").get("DATABASE_URL")
if not OWNER:
    sys.exit("Owner DATABASE_URL not found in the environment or rag/.env")

n = 0


def check(label, ok):
    global n
    n += 1
    assert ok, f"FAILED: {label}"
    print(f"PASS  {label}")


def last_audit(conn):
    return conn.execute(
        "select tool, mode, outcome, reason, customer_id, clause_id from ops.audit_log order by audit_id desc limit 1"
    ).fetchone()


BASE = 0  # requests that already existed for cust_001 before this test, so leftovers do not matter


def status_of(conn, cust="cust_001"):
    rows = conn.execute("select status from ops.deletion_requests where customer_id=%s order by requested_at", (cust,)).fetchall()
    return sorted(r[0] for r in rows[BASE:])  # rows made in one transaction share a timestamp, so order them by name


with db_write.connect() as conn:
    BASE = conn.execute("select count(*) from ops.deletion_requests where customer_id='cust_001'").fetchone()[0]
    assert conn.execute("select count(*) from ops.deletion_requests where customer_id='cust_001' "
                        "and status in ('requested','approved')").fetchone()[0] == 0, "an open request already exists for cust_001"
    base_audit = conn.execute("select count(*) from ops.audit_log").fetchone()[0]
    cust_before = conn.execute("select count(*) from customers").fetchone()[0]
    orders_before = conn.execute("select count(*) from orders").fetchone()[0]

    r = privacy.request_deletion(conn, "cust_001")
    check("a deletion request is opened and is only 'requested'", r["status"] == "requested" and r["kind"] == "deletion" and r["request_id"])
    check("the answer says nothing was deleted", "Nothing has been deleted" in r["next_step"])
    check("the stored request is 'requested'", status_of(conn) == ["requested"])
    check("the audit row says allowed, with the clause",
          last_audit(conn) == ("request_account_deletion", "commit", "allowed", None, "cust_001", "tos_v3 5.2"))
    check("no customer or order row was touched",
          conn.execute("select count(*) from customers").fetchone()[0] == cust_before
          and conn.execute("select count(*) from orders").fetchone()[0] == orders_before)

    r2 = privacy.request_deletion(conn, "cust_001")
    check("a second open request for the same customer is refused", r2 == {"status": "refused", "reason": "request_already_open"})
    check("and the refusal is audited", last_audit(conn)[2:4] == ("refused", "request_already_open"))
    check("the first request is still there, unchanged", status_of(conn) == ["requested"])

    check("an unknown customer is refused", privacy.request_deletion(conn, "cust_999") == {"status": "refused", "reason": "customer_not_found"})

    c = privacy.cancel_deletion(conn, "cust_001")
    check("cancelling stops the open request", c["status"] == "cancelled" and c["request_id"] == r["request_id"])
    check("the stored request is now 'cancelled' and the audit row says allowed",
          status_of(conn) == ["cancelled"] and last_audit(conn)[:3] == ("cancel_deletion_request", "commit", "allowed"))
    check("cancelling again is refused: no open request",
          privacy.cancel_deletion(conn, "cust_001") == {"status": "refused", "reason": "no_open_request"})
    check("cancelling for an unknown customer is refused",
          privacy.cancel_deletion(conn, "cust_999") == {"status": "refused", "reason": "customer_not_found"})

    r3 = privacy.request_deletion(conn, "cust_001")
    check("after a cancellation a new request can be opened", r3["status"] == "requested" and status_of(conn) == ["cancelled", "requested"])
    check("all 7 attempts left an audit row", conn.execute("select count(*) from ops.audit_log").fetchone()[0] == base_audit + 7)
    conn.rollback()

with psycopg.connect(OWNER) as conn:
    BASE = conn.execute("select count(*) from ops.deletion_requests where customer_id='cust_001'").fetchone()[0]
    privacy.request_deletion(conn, "cust_001")
    conn.execute("update ops.deletion_requests set status='approved', decided_by='human_1' where customer_id='cust_001' and status='requested'")
    check("an approved request, in its waiting period, can still be cancelled",
          privacy.cancel_deletion(conn, "cust_001")["status"] == "cancelled" and status_of(conn) == ["cancelled"])
    conn.rollback()

print(f"\nALL {n} CHECKS PASS")
