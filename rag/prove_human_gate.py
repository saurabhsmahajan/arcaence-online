"""Proves the human gate against the real database: a refund over the limit stops and waits for a person.

What happens, in order:
  1. The billing agent reads desk case D04 (a 540.00 USD refund, over the USD cap) on the rolled-back adapter, and proposes it.
  2. The desk side (login desk_service) puts the proposal in the real review queue.
  3. The desk login tries to decide it, and the database refuses.
  4. A person (the owner login, through review_decide) approves it.
  5. The queue shows the decision with the proposal unchanged; a second decision is refused.
  6. Nothing was executed: the refunds and the audit log are exactly as before.
It leaves ONE approved item in the queue as evidence. Items are never deleted, so run it once.

Set both connection strings in your own shell and never paste them anywhere:
  DESK_SERVICE_DATABASE_URL   the desk_service login
  REVIEW_OWNER_DATABASE_URL   the owner login (the person's)
Run from the rag folder:  uv run python prove_human_gate.py --by "your name"
"""
import argparse
import csv
import os
import sys

import psycopg
from psycopg import errors

from billing_shadow import shadow_billing
from billing_tools import local_tools
from case import new_case_id
from review import enqueue_action
from review_decide import decide, owner_connection
from run_desk_billing_cases import CASES, ROOT

results = []


def step(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    return ok


def money(conn, customer_id):
    refunds = conn.execute("select count(*), coalesce(sum(amount), 0) from ops.refunds where customer_id = %s", (customer_id,)).fetchone()
    audit = conn.execute("select count(*) from ops.audit_log").fetchone()[0]
    return (refunds[0], str(refunds[1]), audit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--by", required=True, help="the name of the person deciding")
    ap.add_argument("--case", default="D04")
    args = ap.parse_args()

    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    desk_url = os.environ.get("DESK_SERVICE_DATABASE_URL")
    if not desk_url:
        sys.exit("Set DESK_SERVICE_DATABASE_URL in your own shell first.")
    owner = owner_connection(os.environ.get("REVIEW_OWNER_DATABASE_URL"))

    with psycopg.connect(desk_url) as c:
        if not step("the desk login is desk_service", c.execute("select current_user").fetchone()[0] == "desk_service"):
            sys.exit(1)

    with open(CASES, newline="", encoding="utf-8-sig") as f:
        case = next(r for r in csv.DictReader(f) if r["id"] == args.case)
    print(f"{case['id']}: {case['message']}")

    out = shadow_billing(case["message"], new_case_id(), case["customer_id"], local_tools(ROOT / "mcp"), today=case["as_of"])
    if not step("the agent proposes the refund and does not settle it", out["record"]["outcome"] == "queued" and len(out["proposals"]) == 1
                and out["refund"] is None, f"outcome={out['record']['outcome']}/{out['record']['reason']}"):
        sys.exit("The agent did not queue this case this time (the model is sampled). Nothing was written. Run it again.")
    proposal = out["proposals"][0]
    print("proposal:", proposal["tool"], proposal["args"])
    before = money(owner, case["customer_id"])
    owner.rollback()

    with psycopg.connect(desk_url) as c:   # commits when the block ends
        item = str(enqueue_action(c, **proposal))
    with psycopg.connect(desk_url) as c:
        row = c.execute("select status, kind, proposed from ops.review_items where item_id = %s", (item,)).fetchone()
    step("the proposal is in the real queue, open, as a proposed action", row and row[0] == "open" and row[1] == "proposed_action", item)

    c = psycopg.connect(desk_url)
    try:
        c.execute("update ops.review_items set status = 'approved', decided_by = 'desk' where item_id = %s", (item,))
        refused = False
    except errors.InsufficientPrivilege:
        refused = True
    finally:
        c.rollback()
        c.close()
    step("the desk login cannot decide it: the database refuses", refused)

    try:
        res = decide(owner, item, "approve", args.by, "Human gate proof: approving records the decision only; nothing is executed.")
        owner.commit()
        step("a person (the owner login) approves it", res["status"] == "approved" and res["decided_by"] == args.by.strip())
    except Exception as exc:  # noqa: BLE001
        owner.rollback()
        step("a person (the owner login) approves it", False, type(exc).__name__)

    row = owner.execute("select status, decided_by, proposed from ops.review_items where item_id = %s", (item,)).fetchone()
    owner.rollback()
    step("the queue shows the decision and the proposal exactly as the agent made it",
         row and row[0] == "approved" and row[1] == args.by.strip() and row[2] == {"tool": proposal["tool"], "args": proposal["args"]})

    try:
        decide(owner, item, "reject", args.by, "second decision")
        owner.commit()
        second = False
    except psycopg.Error:
        owner.rollback()
        second = True
    row = owner.execute("select status from ops.review_items where item_id = %s", (item,)).fetchone()
    owner.rollback()
    step("a second decision is refused and the item stays approved", second and row[0] == "approved")

    after = money(owner, case["customer_id"])
    owner.rollback()
    step("nothing was executed: refunds and audit log are exactly as before", after == before, f"before={before} after={after}")
    owner.close()

    print(f"\nitem {item}")
    print("HUMAN GATE:", "PASS" if all(results) else "FAIL")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
