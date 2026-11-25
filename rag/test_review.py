"""Tests for adding review items. Run from the rag folder: uv run python test_review.py
Connects with DATABASE_URL and rolls everything back, so it leaves no rows behind."""
import os

import psycopg
from dotenv import load_dotenv

from review import enqueue_action, enqueue_answer

load_dotenv()
n = 0
CASE = "case_20261125_dddddddddddd"


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


res = {"question": "My lawyer will be in touch", "case_id": CASE, "answer": "fixed reply",
       "handoff": {"needed": True, "reason": "hostile"}}

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    try:
        a = enqueue_answer(conn, res)
        check("an answer item is added", a is not None)
        row = conn.execute("select kind, reason, status, question, summary from ops.review_items where item_id=%s", (a,)).fetchone()
        check("it carries the reason, question and the reply the customer saw",
              row == ("answer", "hostile", "open", "My lawyer will be in touch", "fixed reply"))
        check("adding the same case again returns the same item", enqueue_answer(conn, res) == a)
        check("and adds no copy",
              conn.execute("select count(*) from ops.review_items where case_id=%s", (CASE,)).fetchone()[0] == 1)
        try:
            enqueue_answer(conn, {**res, "handoff": {"needed": False, "reason": ""}})
            check("a result that needs no review is refused", False)
        except ValueError:
            check("a result that needs no review is refused", True)
        p = enqueue_action(conn, CASE, "refund me", "refund 19.00 on ord_0001", "refund_order",
                           {"order_id": "ord_0001", "amount": "19.00"})
        check("a proposed action is added", p is not None)
        row = conn.execute("select kind, status, proposed->>'tool' from ops.review_items where item_id=%s", (p,)).fetchone()
        check("it keeps the tool and starts open", row == ("proposed_action", "open", "refund_order"))
    finally:
        conn.rollback()
print(f"\n{n} checks passed")
