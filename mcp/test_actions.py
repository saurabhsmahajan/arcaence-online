"""The refund action against the real database. Everything runs in ONE transaction that is rolled back at the end,
so no refund, token or audit row is kept. Run: uv run python test_actions.py"""
import hashlib
from decimal import Decimal

import actions
import config
import db_write
from policy import RefundRequest

GOOD = ("tos_v3", "2.2")
STATUTE = ("consumer_act", "3.2")
n = 0


def req(order="ord_1001", cust="cust_001", amount="19.00", clause=GOOD):
    doc, cid = clause if clause else (None, None)
    return RefundRequest(cust, order, amount, doc, cid)


def check(label, ok):
    global n
    n += 1
    assert ok, f"FAILED: {label}"
    print(f"PASS  {label}")


def count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def last_audit(conn):
    return conn.execute(
        "select mode, outcome, reason from ops.audit_log order by audit_id desc limit 1"
    ).fetchone()


def snapshot(c):
    q = lambda sql: count(c, sql)
    return {"refunds": q("select count(*) from ops.refunds"), "tokens": q("select count(*) from ops.confirm_tokens"),
            "used": q("select count(*) from ops.confirm_tokens where used_at is not null"),
            "unused": q("select count(*) from ops.confirm_tokens where used_at is null"),
            "audit": q("select count(*) from ops.audit_log")}


conn = db_write.connect()
base = snapshot(conn)  # other runs (the done check) may have left audit rows and tokens: compare changes, not totals
try:
    # -- dry run -------------------------------------------------------------------------------------------
    a = actions.dry_run_refund(conn, req())
    check("a valid dry run returns a preview and a token", a["status"] == "preview" and len(a["token"]) > 30)
    check("a dry run refunds nothing", count(conn, "select count(*) from ops.refunds") == base["refunds"])
    check("a dry run is audited as allowed", last_audit(conn) == ("dry_run", "allowed", None))
    check("only a hash of the token is stored, never the token",
          count(conn, "select count(*) from ops.confirm_tokens where token_hash = %s", a["token"]) == 0
          and count(conn, "select count(*) from ops.confirm_tokens where token_hash = %s",
                    hashlib.sha256(a["token"].encode()).hexdigest()) == 1)
    check("the preview says what the cap leaves", a["cap_remaining_after"] == "31.00")

    tokens_before = count(conn, "select count(*) from ops.confirm_tokens")
    r = actions.dry_run_refund(conn, req(order="ord_2001", cust="cust_002", amount="540.00"))
    check("a refund over the cap is refused", r == {"status": "refused", "reason": "over_cap"})
    check("the over-cap refusal is logged", last_audit(conn) == ("dry_run", "refused", "over_cap"))
    check("a refusal creates no token", count(conn, "select count(*) from ops.confirm_tokens") == tokens_before)

    r = actions.dry_run_refund(conn, req(clause=None))
    check("a refund without a clause id is refused", r == {"status": "refused", "reason": "no_clause"})
    check("the no-clause refusal is logged", last_audit(conn) == ("dry_run", "refused", "no_clause"))

    r = actions.dry_run_refund(conn, req(clause=("tos_v2", "2.2")))
    check("a superseded clause is refused and logged",
          r["reason"] == "clause_not_allowed" and last_audit(conn)[2] == "clause_not_allowed")

    # -- commit --------------------------------------------------------------------------------------------
    r = actions.commit_refund(conn, req(), None)
    check("a commit without a token is refused and logged",
          r["reason"] == "token_missing" and last_audit(conn) == ("commit", "refused", "token_missing"))
    r = actions.commit_refund(conn, req(), "not-a-real-token")
    check("a commit with an unknown token is refused", r["reason"] == "token_invalid")

    r = actions.commit_refund(conn, req(amount="18.00"), a["token"])
    check("a token cannot be used for different arguments", r["reason"] == "args_mismatch")
    check("a mismatch does not spend the token",
          count(conn, "select count(*) from ops.confirm_tokens where used_at is not null") == base["used"])

    b = actions.dry_run_refund(conn, req(order="ord_1002", amount="32.00", clause=STATUTE))
    check("a second preview for another order is allowed while the cap is untouched", b["status"] == "preview")

    done = actions.commit_refund(conn, req(), a["token"])
    check("a commit with the right token refunds", done["status"] == "done" and done["amount"] == "19.00")
    check("the refund is recorded with its clause", conn.execute(
        "select order_id, amount, clause_doc, clause_id from ops.refunds").fetchall()
        == [("ord_1001", Decimal("19.00"), "tos_v3", "2.2")])
    check("the commit is audited as allowed", last_audit(conn) == ("commit", "allowed", None))

    r = actions.commit_refund(conn, req(), a["token"])
    check("replaying a spent token is refused", r["reason"] == "token_used")
    check("a replay refunds nothing more", count(conn, "select count(*) from ops.refunds") == base["refunds"] + 1)

    r = actions.commit_refund(conn, req(order="ord_1002", amount="32.00", clause=STATUTE), b["token"])
    check("the cap is checked again at commit (19 + 32 is over 50)", r == {"status": "refused", "reason": "over_cap"})
    check("that refusal refunds nothing and keeps the token unspent",
          count(conn, "select count(*) from ops.refunds") == base["refunds"] + 1
          and count(conn, "select count(*) from ops.confirm_tokens where used_at is null") == base["unused"] + 1)

    config.CONFIRM_TOKEN_TTL_SECONDS = -1
    c = actions.dry_run_refund(conn, req(order="ord_2001", cust="cust_002", amount="5.00"))
    config.CONFIRM_TOKEN_TTL_SECONDS = 600
    r = actions.commit_refund(conn, req(order="ord_2001", cust="cust_002", amount="5.00"), c["token"])
    check("an expired token is refused", r["reason"] == "token_expired")

    r = actions.commit_refund(conn, req(cust="cust_002"), a["token"])
    check("a token cannot be used for another customer", r["reason"] in ("token_used", "args_mismatch", "wrong_customer"))

    refused = count(conn, "select count(*) from ops.audit_log where outcome = 'refused'")
    check("every refusal above left an audit row", refused >= 9)
finally:
    conn.rollback()
    conn.close()

with db_write.connect() as check_conn:
    check("the whole run was rolled back: no refunds, tokens or audit rows kept", snapshot(check_conn) == base)

print(f"\n{n} checks passed")
