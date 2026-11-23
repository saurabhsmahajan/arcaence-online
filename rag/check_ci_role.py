"""Proves the ci_eval login can do what the gate needs and nothing more.

Run from the rag folder with DATABASE_URL set to the ci_eval connection string:
  uv run python check_ci_role.py
Set the variable in your own shell. Never paste the connection string anywhere else.
"""
import os
import sys

import psycopg
from psycopg import errors

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("Set DATABASE_URL to the ci_eval connection string first.")

failures = []


def run(name, sql, expect_error=None, params=None, rw=False):
    """expect_error=None: must succeed. Otherwise the call must fail with that error class.

    Nothing is ever committed: every probe is rolled back, so even a wrongly configured
    role cannot change data through this script.
    rw=True first switches the transaction to read-write. The read-only default is only a
    default (a login can override it for its own session), so the write probes must be
    refused by privileges, not by that setting.
    """
    conn = psycopg.connect(url)
    rows = None
    try:
        if rw:
            conn.execute("set transaction read write")
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


who = run("connects as ci_eval", "select current_user")
print("     current_user:", who[0][0] if who else "?")
if who and who[0][0] != "ci_eval":
    failures.append("wrong login: expected ci_eval")

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

run("cannot read customers", "select * from customers limit 1", errors.InsufficientPrivilege)
run("cannot read ops.audit_log", "select * from ops.audit_log limit 1", errors.InsufficientPrivilege)
run("cannot write documents (read-write requested)", "insert into documents (doc_id) values ('x')", errors.InsufficientPrivilege, rw=True)
run("cannot write plans_fees (read-write requested)", "delete from plans_fees where false", errors.InsufficientPrivilege, rw=True)
rows = run("session is read-only", "show transaction_read_only")
if rows and rows[0][0] != "on":
    print("FAIL transaction_read_only is", rows[0][0])
    failures.append("not read-only")

print("\n" + ("CI ROLE CHECK: PASS" if not failures else f"CI ROLE CHECK: FAIL {failures}"))
sys.exit(1 if failures else 0)
