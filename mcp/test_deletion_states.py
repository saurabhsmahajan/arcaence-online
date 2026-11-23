"""Checks for the deletion-request state rules in the database (migration 010).
Every statement runs inside a transaction that is rolled back, so nothing is left behind.
Needs OPS_WRITER_DATABASE_URL (mcp/.env) and the owner URL, read as DATABASE_URL from the environment or rag/.env.
Run from the mcp folder: uv run python test_deletion_states.py"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values, load_dotenv

load_dotenv()
WRITER = os.environ["OPS_WRITER_DATABASE_URL"]
OWNER = os.environ.get("DATABASE_URL") or dotenv_values(Path(__file__).resolve().parent.parent / "rag" / ".env").get("DATABASE_URL")
if not OWNER:
    sys.exit("Owner DATABASE_URL not found in the environment or rag/.env")

NEW = "insert into ops.deletion_requests (customer_id, reason) values ('cust_001', 'test')"
APPROVE = "update ops.deletion_requests set status='approved', decided_by='human_1' where customer_id='cust_001' and status='requested'"
COMPLETE = "update ops.deletion_requests set status='completed', completed_by='human_1' where customer_id='cust_001' and status='approved'"
# the only way a test can pass time: switch the guard off for one statement, inside the rolled-back transaction
BACKDATE = ("alter table ops.deletion_requests disable trigger deletion_requests_row_guard;"
            "update ops.deletion_requests set cooling_off_until = now() - interval '1 day' where customer_id='cust_001' and status='approved';"
            "alter table ops.deletion_requests enable trigger deletion_requests_row_guard")

fails = 0


def run(url, steps):
    """Run the steps in one transaction and roll back. Returns None if all worked, else the error text."""
    with psycopg.connect(url) as conn:
        try:
            for s in steps:
                conn.execute(s)
        except psycopg.Error as e:
            conn.rollback()
            return str(e)
        conn.rollback()
        return None


def check(label, url, steps, expect_error=None):
    global fails
    err = run(url, steps)
    if expect_error is None:
        ok = err is None
    else:
        ok = err is not None and expect_error.lower() in err.lower()
    if not ok:
        fails += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got: {err!r}"))


# --- the write login: can ask, can cancel, can do nothing else ---
check("writer can create a request", WRITER, [NEW])
check("a request cannot start already approved", WRITER,
      ["insert into ops.deletion_requests (customer_id, status) values ('cust_001', 'approved')"], "starts as requested")
check("writer cannot approve", WRITER, [NEW, APPROVE], "permission denied")
check("writer cannot complete", WRITER, [NEW, COMPLETE], "permission denied")
check("writer can cancel its own request", WRITER,
      [NEW, "update ops.deletion_requests set status='cancelled', cancelled_by='ops_writer' where customer_id='cust_001' and status='requested'"])
check("writer cannot edit the reason", WRITER, [NEW, "update ops.deletion_requests set reason='x' where customer_id='cust_001'"], "permission denied")
check("writer cannot delete a request", WRITER, [NEW, "delete from ops.deletion_requests where customer_id='cust_001'"], "permission denied")
check("writer cannot truncate", WRITER, ["truncate ops.deletion_requests"], "permission denied")
check("only one open request per customer", WRITER, [NEW, NEW], "duplicate key")

# --- the owner: the human steps, and the rules that hold even for the owner ---
check("a request cannot jump from requested to completed", OWNER, [NEW,
      "update ops.deletion_requests set status='completed', completed_by='human_1' where customer_id='cust_001' and status='requested'"],
      "cannot go from requested to completed")
check("approval needs a name", OWNER, [NEW, "update ops.deletion_requests set status='approved' where customer_id='cust_001' and status='requested'"], "decided_by")
check("approval works and starts the window", OWNER, [
    NEW, APPROVE,
    "do $$ begin if not exists (select 1 from ops.deletion_requests where status='approved' "
    "and cooling_off_until > now() + interval '6 days 23 hours' and decided_at is not null) "
    "then raise exception 'window not set'; end if; end $$"])
check("completion is refused inside the cooling-off window", OWNER, [NEW, APPROVE, COMPLETE], "cooling-off window is not over")
check("completion works after the window", OWNER, [NEW, APPROVE, BACKDATE, COMPLETE])
check("a completed request is final", OWNER, [NEW, APPROVE, BACKDATE, COMPLETE,
      "update ops.deletion_requests set status='cancelled', cancelled_by='h' where customer_id='cust_001' and status='completed'"], "is final")
check("an approved request can still be cancelled", OWNER, [NEW, APPROVE,
      "update ops.deletion_requests set status='cancelled', cancelled_by='cust_001' where customer_id='cust_001' and status='approved'"])
check("the window cannot be shortened after approval", OWNER, [NEW, APPROVE,
      "update ops.deletion_requests set status='completed', completed_by='h', cooling_off_until=now() - interval '1 day' where customer_id='cust_001' and status='approved'"],
      "cooling-off window is not over")
check("the owner cannot delete a request either", OWNER, [NEW, "delete from ops.deletion_requests where customer_id='cust_001'"], "never deleted")

# --- the done check at the data level: nothing in the customer tables moves ---
with psycopg.connect(OWNER) as conn:
    before = conn.execute("select count(*) from customers").fetchone()[0], conn.execute("select count(*) from orders").fetchone()[0]
check("the whole flow touches no customer data", OWNER, [NEW, APPROVE, BACKDATE, COMPLETE])
with psycopg.connect(OWNER) as conn:
    after = conn.execute("select count(*) from customers").fetchone()[0], conn.execute("select count(*) from orders").fetchone()[0]
if before != after:
    fails += 1
print(f"{'PASS' if before == after else 'FAIL'}  customer and order counts unchanged: {before} then {after}")

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
