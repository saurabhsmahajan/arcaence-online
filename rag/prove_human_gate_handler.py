"""Proves the human gate THROUGH THE HANDLER against the real database: a refund over the limit stops and waits for a person.

prove_human_gate.py queued the proposal itself, standing in for the handler. This script does not: it sends desk case D04 (a
540.00 USD refund, over the USD cap) through handle_message with HUMAN_GATE_QUEUE=on, so the handler's own code puts the proposal
in the real review queue. Then:
  1. the handler reports the proposal queued, and the reply and the money are untouched (shadow billing never refunds);
  2. the proposal is in the real queue, open, exactly as the agent made it, under the case's own id;
  3. the desk login tries to decide it, and the database refuses;
  4. a person (the owner login, through review_decide) approves it;
  5. the queue shows the decision and the proposal unchanged; a second decision is refused;
  6. nothing was executed: refunds and audit log are exactly as before.
It leaves items in the queue as evidence: the approved proposal, and the routing note the handler adds for every routed case.
Items are never deleted. Each run adds them again, so run it once.

Set both connection strings in your own shell and never paste them anywhere:
  DESK_SERVICE_DATABASE_URL   the desk_service login (the handler writes with it)
  REVIEW_OWNER_DATABASE_URL   the owner login (the person's)
Run from the rag folder:  uv run python prove_human_gate_handler.py --by "your name"
"""
import argparse
import csv
import os
import sys

import psycopg
from psycopg import errors

from billing_shadow import shadow_billing
from billing_tools import local_tools
from handler import handle_message
from prove_human_gate import money
from review_decide import decide, owner_connection
from run_desk_billing_cases import CASES, ROOT

results = []


def step(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    return ok


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
    before = money(owner, case["customer_id"])
    owner.rollback()

    def billing_fn(question, case_id, customer_id):
        return shadow_billing(question, case_id, customer_id, local_tools(ROOT / "mcp"), today=case["as_of"])

    old = {k: os.environ.get(k) for k in ("DATABASE_URL", "HUMAN_GATE_QUEUE")}
    os.environ["DATABASE_URL"] = desk_url          # the handler's own writers read this: it is the desk_service login
    os.environ["HUMAN_GATE_QUEUE"] = "on"
    try:
        result = handle_message(case["message"], trace_fn=lambda r, ms: None, customer_id=case["customer_id"], billing_fn=billing_fn)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    b = result["billing"]
    if not step("the handler ran billing and it proposed the refund", b["ran"] and b["would_queue"] and b["outcome"] == "queued",
                f"outcome={b['outcome']}/{b['reason']} error={b['error'] or '-'}"):
        sys.exit("The agent did not queue this case this time (the model is sampled), or billing did not run. "
                 "The handler may still have added a routing note. Run it again.")
    step("the handler queued the proposal by itself", b["proposal_queued"] and b["proposal_item_id"] and not b["proposal_error"],
         f"item={b['proposal_item_id']} error={b['proposal_error'] or '-'}")
    step("shadow billing recorded no refund and the reply is the desk's own", b["would_refund"] is False and isinstance(result["answer"], str),
         f"behavior={result['behavior']}")
    item = b["proposal_item_id"]
    if not item:
        sys.exit(1)

    with psycopg.connect(desk_url) as c:
        row = c.execute("select status, kind, case_id, proposed from ops.review_items where item_id = %s", (item,)).fetchone()
        others = c.execute("select kind, proposed->>'tool' from ops.review_items where case_id = %s and item_id <> %s", (result["case_id"], item)).fetchall()
    proposed = row[3] if row else {}
    args_ = (proposed or {}).get("args", {})
    step("the proposal is in the real queue, open, under the case's own id",
         row and row[0] == "open" and row[1] == "proposed_action" and row[2] == result["case_id"], item)
    step("and it is exactly the refund the agent proposed: issue_refund, customer, order, amount, clause",
         (proposed or {}).get("tool") == "issue_refund" and args_.get("customer_id") == case["customer_id"]
         and args_.get("order_id") == "ord_2001" and args_.get("amount") == "540.00" and args_.get("clause_id") == "3.3", str(args_))
    print("other items the handler added for this case:", others or "none")

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
        res = decide(owner, item, "approve", args.by, "Human gate proof through the handler: approving records the decision only; nothing is executed.")
        owner.commit()
        step("a person (the owner login) approves it", res["status"] == "approved" and res["decided_by"] == args.by.strip())
    except Exception as exc:  # noqa: BLE001
        owner.rollback()
        step("a person (the owner login) approves it", False, type(exc).__name__)

    row = owner.execute("select status, decided_by, proposed from ops.review_items where item_id = %s", (item,)).fetchone()
    owner.rollback()
    step("the queue shows the decision and the proposal exactly as the agent made it",
         row and row[0] == "approved" and row[1] == args.by.strip() and row[2] == proposed)

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

    print(f"\nitem {item}  case {result['case_id']}")
    print("HUMAN GATE THROUGH THE HANDLER:", "PASS" if all(results) else "FAIL")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
