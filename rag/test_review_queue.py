"""Tests for the review queue guard. Run from the rag folder: uv run python test_review_queue.py
Connects as the database owner and rolls everything back, so it leaves no rows behind."""
import json
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
n = 0
CASE = "case_20261125_aaaaaaaaaaaa"
CASE2 = "case_20261125_bbbbbbbbbbbb"


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


def add(conn, case, kind="answer", reason="hostile", proposed=None, status="open", **extra):
    cols = {"case_id": case, "kind": kind, "reason": reason, "question": "q", "summary": "s",
            "proposed": json.dumps(proposed) if proposed is not None else None, "status": status, **extra}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return conn.execute(f"insert into ops.review_items ({names}) values ({marks}) returning item_id",
                        list(cols.values())).fetchone()[0]


def refused(conn, sql, params=()):
    """True if the database refused the statement. Each attempt is a savepoint, so the run goes on."""
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error:
        return True
    return False


def decide(conn, item, status, by="saurabh"):
    return refused(conn, "update ops.review_items set status=%s, decided_by=%s where item_id=%s",
                   (status, by, item)) is False


with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    try:
        a = add(conn, CASE)
        check("an answer item can be added", a is not None)
        check("it starts open", conn.execute("select status from ops.review_items where item_id=%s", (a,)).fetchone()[0] == "open")
        check("a second answer item for the same case is refused",
              refused(conn, "insert into ops.review_items (case_id,kind,reason,question,summary) values (%s,'answer','hostile','q','s')", (CASE,)))
        check("a badly shaped case id is refused",
              refused(conn, "insert into ops.review_items (case_id,kind,reason,question,summary) values ('case_1','answer','hostile','q','s')"))
        check("an unknown kind is refused",
              refused(conn, "insert into ops.review_items (case_id,kind,reason,question,summary) values (%s,'other','hostile','q','s')", (CASE2,)))
        check("an unknown reason is refused",
              refused(conn, "insert into ops.review_items (case_id,kind,reason,question,summary) values (%s,'answer','bored','q','s')", (CASE2,)))
        check("an item cannot start decided",
              refused(conn, "insert into ops.review_items (case_id,kind,reason,question,summary,status,decided_by,decided_at) values (%s,'answer','hostile','q','s','resolved','x',now())", (CASE2,)))
        check("an action item without a proposal is refused",
              refused(conn, "insert into ops.review_items (case_id,kind,reason,question,summary) values (%s,'proposed_action','proposed_action','q','s')", (CASE2,)))
        check("an answer item that carries a proposal is refused",
              refused(conn, "insert into ops.review_items (case_id,kind,reason,question,summary,proposed) values (%s,'answer','hostile','q','s','{}')", (CASE2,)))

        check("an answer cannot be approved", not decide(conn, a, "approved"))
        check("an answer cannot be rejected", not decide(conn, a, "rejected"))
        check("a decision needs a name",
              refused(conn, "update ops.review_items set status='resolved' where item_id=%s", (a,)))
        check("a blank name is refused", not decide(conn, a, "resolved", by="   "))
        check("the question cannot be rewritten",
              refused(conn, "update ops.review_items set question='changed' where item_id=%s", (a,)))
        check("the case id cannot be changed",
              refused(conn, "update ops.review_items set case_id=%s where item_id=%s", (CASE2, a)))
        check("a person can resolve an answer", decide(conn, a, "resolved"))
        check("the decision time is set by the database",
              conn.execute("select decided_at is not null from ops.review_items where item_id=%s", (a,)).fetchone()[0])
        check("a resolved item is final", not decide(conn, a, "approved"))
        check("a record is never deleted", refused(conn, "delete from ops.review_items where item_id=%s", (a,)))
        check("the table cannot be truncated", refused(conn, "truncate ops.review_items"))

        act = {"tool": "refund_order", "args": {"order_id": "ord_0001", "amount": "19.00"}}
        p = add(conn, CASE2, kind="proposed_action", reason="proposed_action", proposed=act)
        check("an action item can be added with its proposal", p is not None)
        check("an action cannot be marked resolved", not decide(conn, p, "resolved"))
        check("the proposal cannot be rewritten",
              refused(conn, "update ops.review_items set proposed='{}' where item_id=%s", (p,)))
        check("a person can approve an action", decide(conn, p, "approved"))
        check("an approved action is final", not decide(conn, p, "rejected"))
        p2 = add(conn, CASE2, kind="proposed_action", reason="proposed_action", proposed=act)
        check("several action items for one case are allowed", p2 is not None)
        check("a person can reject an action", decide(conn, p2, "rejected"))
    finally:
        conn.rollback()
print(f"\n{n} checks passed")
