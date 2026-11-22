"""The cancel_subscription action against the real database. One transaction, rolled back at the end.
Run: uv run python test_cancel.py"""
import actions
import db_write
from policy import CancelFacts, CancelRequest, check_cancel

OK = ("tos_v3", "3.2")
n = 0


def req(order="ord_1001", cust="cust_001", clause=OK):
    doc, cid = clause if clause else (None, None)
    return CancelRequest(cust, order, doc, cid)


def check(label, ok):
    global n
    n += 1
    assert ok, f"FAILED: {label}"
    print(f"PASS  {label}")


def count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def last_audit(conn):
    return conn.execute(
        "select tool, mode, outcome, reason from ops.audit_log order by audit_id desc limit 1"
    ).fetchone()


# -- the pure policy, no database -----------------------------------------------------------------------------
sub = {"order_id": "ord_1001", "customer_id": "cust_001", "kind": "subscription"}
check("policy: a clean request passes", check_cancel(req(), CancelFacts(sub, False)) is None)
check("policy: no clause is refused", check_cancel(req(clause=None), CancelFacts(sub, False)) == "no_clause")
check("policy: an unknown clause is refused", check_cancel(req(clause=("tos_v3", "99.9")), CancelFacts(sub, False)) == "unknown_clause")
check("policy: a refund-only clause is not allowed for cancelling",
      check_cancel(req(clause=("tos_v3", "2.2")), CancelFacts(sub, False)) == "clause_not_allowed")
check("policy: a missing order is refused", check_cancel(req(), CancelFacts(None, False)) == "order_not_found")
check("policy: another customer's order is refused", check_cancel(req(cust="cust_002"), CancelFacts(sub, False)) == "wrong_customer")
check("policy: a one-off order is not a subscription",
      check_cancel(req(), CancelFacts({**sub, "kind": "one_off"}, False)) == "subscription_not_active")
check("policy: an already cancelled subscription is refused", check_cancel(req(), CancelFacts(sub, True)) == "subscription_not_active")

# -- against the database --------------------------------------------------------------------------------------
def snapshot(c):
    q = lambda sql: count(c, sql)
    return {"cancellations": q("select count(*) from ops.cancellations"), "audit": q("select count(*) from ops.audit_log"),
            "used": q("select count(*) from ops.confirm_tokens where used_at is not null")}


conn = db_write.connect()
base = snapshot(conn)  # other runs (the done check) may have left audit rows: compare changes, not totals
try:
    a = actions.dry_run_cancel(conn, req())
    check("a valid dry run returns a preview and a token", a["status"] == "preview" and len(a["token"]) > 30)
    check("a dry run cancels nothing", count(conn, "select count(*) from ops.cancellations") == base["cancellations"])
    check("a dry run is audited as allowed", last_audit(conn) == ("cancel_subscription", "dry_run", "allowed", None))

    r = actions.dry_run_cancel(conn, req(clause=None))
    check("a cancellation without a clause id is refused and logged",
          r["reason"] == "no_clause" and last_audit(conn) == ("cancel_subscription", "dry_run", "refused", "no_clause"))
    r = actions.dry_run_cancel(conn, req(order="ord_1002"))
    check("cancelling a one-off order is refused", r["reason"] == "subscription_not_active")
    r = actions.dry_run_cancel(conn, req(cust="cust_002"))
    check("cancelling another customer's subscription is refused", r["reason"] == "wrong_customer")

    r = actions.commit_cancel(conn, req(), None)
    check("a commit without a token is refused and logged",
          r["reason"] == "token_missing" and last_audit(conn)[2:] == ("refused", "token_missing"))
    r = actions.commit_cancel(conn, req(order="ord_2001", cust="cust_002"), a["token"])
    check("a token cannot be used for another order", r["reason"] == "args_mismatch")
    check("a mismatch does not spend the token",
          count(conn, "select count(*) from ops.confirm_tokens where used_at is not null") == base["used"])

    refund = actions.dry_run_refund(conn, __import__("policy").RefundRequest("cust_001", "ord_1001", "19.00", "tos_v3", "2.2"))
    r = actions.commit_cancel(conn, req(), refund["token"])
    check("a refund token cannot cancel a subscription", r["reason"] in ("token_invalid", "args_mismatch"))

    done = actions.commit_cancel(conn, req(), a["token"])
    check("a commit with the right token cancels", done["status"] == "done")
    check("the cancellation is recorded with its clause", conn.execute(
        "select order_id, clause_doc, clause_id from ops.cancellations").fetchall() == [("ord_1001", "tos_v3", "3.2")])
    check("the commit is audited as allowed", last_audit(conn) == ("cancel_subscription", "commit", "allowed", None))

    r = actions.commit_cancel(conn, req(), a["token"])
    check("replaying a spent token is refused", r["reason"] == "token_used")
    r = actions.dry_run_cancel(conn, req())
    check("a second cancellation of the same subscription is refused", r["reason"] == "subscription_not_active")
    check("only one cancellation exists", count(conn, "select count(*) from ops.cancellations") == base["cancellations"] + 1)
finally:
    conn.rollback()
    conn.close()

with db_write.connect() as c:
    check("the whole run was rolled back", snapshot(c) == base)

print(f"\n{n} checks passed")
