"""Live proof of the write kill switch on the real database. Nothing is written: it runs as the owner inside one
transaction that is always rolled back, and it only tries statements that cannot succeed anyway.

  uv run python prove_kill_switch.py

How it tells the cases apart: an INSERT ... DEFAULT VALUES into a write table fails either way, but with a
different error. Switch ON the table's own constraint complains (not-null, sqlstate 23502). Switch OFF the kill
switch trigger fires first, before any constraint, with sqlstate 55000 and the message 'writes_disabled'.
"""
import os
import sys

from review_decide import owner_connection

WRITE_TABLES = ["ops.refunds", "ops.cancellations", "ops.deletion_requests", "ops.export_requests"]
OPEN_TABLES = ["ops.review_items"]
DISABLED, CONSTRAINT = "55000", "23502"
n = 0


def ok(text):
    global n
    n += 1
    print(f"ok  {n:2} {text}")


def sqlstate(conn, table):
    """The sqlstate of an INSERT DEFAULT VALUES into the table, tried in a savepoint that is rolled back."""
    import psycopg

    conn.execute("savepoint s")
    try:
        conn.execute(f"insert into {table} default values")
        code = "00000"
    except psycopg.Error as exc:
        code = exc.sqlstate or "?"
    conn.execute("rollback to savepoint s")
    return code


def main() -> int:
    conn = owner_connection(os.environ.get("REVIEW_OWNER_DATABASE_URL"))
    try:
        before = conn.execute("select value from ops.system_flags where name = 'writes'").fetchone()
        before = before[0] if before else None
        print(f"flag before: {before!r} (everything below is rolled back)")

        conn.execute("insert into ops.system_flags (name, value, reason) values ('writes', 'on', 'proof') "
                     "on conflict (name) do update set value = 'on', reason = 'proof'")
        assert conn.execute("select ops.writes_enabled()").fetchone()[0] is True
        ok("switch ON: ops.writes_enabled() is true")
        for t in WRITE_TABLES:
            assert sqlstate(conn, t) == CONSTRAINT, f"{t} was blocked while ON"
        ok("switch ON: all four write tables reach their own constraints (not blocked)")

        conn.execute("update ops.system_flags set value = 'off', reason = 'proof' where name = 'writes'")
        assert conn.execute("select ops.writes_enabled()").fetchone()[0] is False
        ok("switch OFF: ops.writes_enabled() is false")
        for t in WRITE_TABLES:
            assert sqlstate(conn, t) == DISABLED, f"{t} was not blocked while OFF"
        ok("switch OFF: refunds, cancellations, deletion requests and export requests are all refused (55000)")
        for t in OPEN_TABLES:
            assert sqlstate(conn, t) == CONSTRAINT, f"{t} was blocked while OFF"
        ok("switch OFF: the review queue is still open (a person can see what is waiting)")
        assert conn.execute("select count(*) from ops.audit_log").fetchone()[0] >= 0
        ok("switch OFF: the audit log can still be read")

        conn.execute("delete from ops.system_flags where name = 'writes'")
        assert conn.execute("select ops.writes_enabled()").fetchone()[0] is False
        for t in WRITE_TABLES:
            assert sqlstate(conn, t) == DISABLED, f"{t} was not blocked with no flag row"
        ok("no flag row: writes are OFF on all four tables (fails closed)")

        hist = conn.execute("select count(*) from ops.system_flag_history where reason in ('proof', 'flag row deleted')").fetchone()[0]
        assert hist >= 3
        ok("every flip above was recorded in ops.system_flag_history")
    finally:
        conn.rollback()
        after = conn.execute("select value from ops.system_flags where name = 'writes'").fetchone()
        after = after[0] if after else None
        conn.close()
    assert after == before, f"flag changed from {before!r} to {after!r}"
    ok(f"rolled back: the flag is still {after!r}")
    print(f"\nKILL SWITCH PROOF: PASS ({n} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
