"""The data export request: the action against the real database, and the rules in migration 011.
Everything runs in a transaction that is rolled back. Run from the mcp folder: uv run python test_privacy_export.py"""
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


# -- the action, as the write login ---------------------------------------------------------------------------
with db_write.connect() as conn:
    base_audit = conn.execute("select count(*) from ops.audit_log").fetchone()[0]

    r = privacy.request_export(conn, "cust_001")
    check("a request for a real customer is opened", r["status"] == "requested" and r["kind"] == "export" and r["request_id"])
    check("the answer is counts only: 2 orders and 2 invoices for cust_001", r["inventory"] == {"orders": 2, "invoices": 2})
    check("the answer carries no personal data fields", set(r) == {"status", "kind", "request_id", "inventory", "next_step"})
    check("the audit row says allowed, with the clause",
          last_audit(conn) == ("request_data_export", "commit", "allowed", None, "cust_001", "tos_v3 5.2"))

    r2 = privacy.request_export(conn, "cust_001")
    check("a second open request for the same customer is refused", r2 == {"status": "refused", "reason": "request_already_open"})
    check("and the refusal is audited", last_audit(conn)[2:4] == ("refused", "request_already_open"))
    check("the refused attempt left exactly one open request",
          conn.execute("select count(*) from ops.export_requests where customer_id='cust_001'").fetchone()[0] == 1)

    r3 = privacy.request_export(conn, "cust_999")
    check("an unknown customer is refused", r3 == {"status": "refused", "reason": "customer_not_found"})
    check("and nothing was opened for them",
          conn.execute("select count(*) from ops.export_requests where customer_id='cust_999'").fetchone()[0] == 0)

    check("three attempts wrote three audit rows",
          conn.execute("select count(*) from ops.audit_log").fetchone()[0] == base_audit + 3)
    conn.rollback()

# -- the rules in the database ---------------------------------------------------------------------------------
NEW = "insert into ops.export_requests (customer_id) values ('cust_001')"


def refused(url, steps, text):
    with psycopg.connect(url) as conn:
        try:
            for s in steps:
                conn.execute(s)
        except psycopg.Error as e:
            conn.rollback()
            return text.lower() in str(e).lower()
        conn.rollback()
        return False


def worked(url, steps):
    with psycopg.connect(url) as conn:
        for s in steps:
            conn.execute(s)
        conn.rollback()
    return True


WRITER = os.environ["OPS_WRITER_DATABASE_URL"]
check("writer cannot decide a request", refused(WRITER, [NEW, "update ops.export_requests set status='fulfilled'"], "permission denied"))
check("writer cannot delete a request", refused(WRITER, [NEW, "delete from ops.export_requests"], "permission denied"))
check("a request cannot start as fulfilled",
      refused(WRITER, ["insert into ops.export_requests (customer_id, status) values ('cust_001','fulfilled')"], "starts as requested"))
check("the owner can fulfil a request with a name",
      worked(OWNER, [NEW, "update ops.export_requests set status='fulfilled', decided_by='human_1'"]))
check("a decision needs a name", refused(OWNER, [NEW, "update ops.export_requests set status='fulfilled'"], "decided_by"))
check("a decided request is final",
      refused(OWNER, [NEW, "update ops.export_requests set status='rejected', decided_by='h'",
                      "update ops.export_requests set status='fulfilled', decided_by='h'"], "is final"))
check("the owner cannot delete a request either", refused(OWNER, [NEW, "delete from ops.export_requests"], "never deleted"))

print(f"\nALL {n} CHECKS PASS")
