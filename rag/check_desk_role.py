"""Proves the desk_service login can do what the desk needs and nothing more.

Run from the rag folder with DATABASE_URL set to the desk_service connection string:
  uv run python check_desk_role.py
Set the variable in your own shell. Never paste the connection string anywhere else.
Nothing is ever committed: every probe is rolled back.
"""
import os
import sys

import psycopg
from psycopg import errors

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("Set DATABASE_URL to the desk_service connection string first.")

failures = []
ROW = ("insert into ops.review_items (case_id, kind, reason, question, summary) "
       "values ('case_20261125_cccccccccccc', 'answer', 'hostile', 'probe', 'probe')")


def run(name, sql, expect_error=None, params=None):
    """expect_error=None: must succeed. Otherwise the call must fail with that error class."""
    conn = psycopg.connect(url)
    rows = None
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall() if cur.description else []
        err = None
    except psycopg.Error as exc:
        err = exc
    finally:
        conn.rollback()
        conn.close()
    if err is not None:
        ok = expect_error is not None and isinstance(err, expect_error)
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  ({type(err).__name__}: {err})"))
        if not ok:
            failures.append(name)
        return None
    ok = expect_error is None
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else "  (it succeeded, it should have been refused)"))
    if not ok:
        failures.append(name)
    return rows


who = run("connects as desk_service", "select current_user")
print("     current_user:", who[0][0] if who else "?")
if who and who[0][0] != "desk_service":
    failures.append("wrong login: expected desk_service")

for t in ("documents", "chunks", "clause_registry", "plans_fees"):
    rows = run(f"reads {t}", f"select count(*) from {t}")
    if rows and rows[0][0] == 0:
        print(f"FAIL {t} is empty for this login (missing policy?)")
        failures.append(f"{t} empty")

zero = "[" + ",".join(["0"] * 384) + "]"
rows = run("calls search_policy", "select count(*) from search_policy(%s::vector, 3)", params=(zero,))
if rows and rows[0][0] == 0:
    print("FAIL search_policy returned nothing")
    failures.append("search_policy empty")

run("can add a review item", ROW)
run("can read the review queue", "select count(*) from ops.review_items")
run("cannot decide an item", "update ops.review_items set status='resolved', decided_by='x' where false", errors.InsufficientPrivilege)
run("cannot delete an item", "delete from ops.review_items where false", errors.InsufficientPrivilege)
run("cannot read customers", "select * from customers limit 1", errors.InsufficientPrivilege)
run("cannot read ops.audit_log", "select * from ops.audit_log limit 1", errors.InsufficientPrivilege)
run("cannot read ops.refunds", "select * from ops.refunds limit 1", errors.InsufficientPrivilege)
run("cannot write documents", "insert into documents (doc_id) values ('x')", errors.InsufficientPrivilege)
run("cannot write plans_fees", "delete from plans_fees where false", errors.InsufficientPrivilege)

print("\n" + ("DESK ROLE CHECK: PASS" if not failures else f"DESK ROLE CHECK: FAIL {failures}"))
sys.exit(1 if failures else 0)
