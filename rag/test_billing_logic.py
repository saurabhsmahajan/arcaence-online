"""Tests for the billing contract. No model, no database, no MCP, no keys."""
from billing_logic import (AGENT_CLOSES, CUSTOMER_REFUSALS, MAX_STEPS, MODEL_TOOLS, OUTCOMES, QUEUE_REASONS, STEP_TOOLS,
                           CaseRecord, StepLimitReached, close_case_problems, next_after_dry_run, outcome_after_commit,
                           refund_args_problems, refund_proposal)

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception:
        return False
    return False


CASE = "case_20261127_0123456789ab"
CUST = "cust_001"


def rec(**kw):
    return CaseRecord(CASE, CUST, **kw)


def args(**kw):
    base = {"order_id": "ord_1042", "amount": "19.00", "clause_doc": "tos_v3", "clause_id": "2.2"}
    base.update(kw)
    return base


# the tool lists
check("request_refund" in MODEL_TOOLS and "issue_refund" not in MODEL_TOOLS, "the model asks for request_refund, never issue_refund")
check("issue_refund" in STEP_TOOLS and "request_refund" not in STEP_TOOLS, "the record names the tool that ran")
check("cancel_subscription" not in MODEL_TOOLS and "request_account_deletion" not in MODEL_TOOLS, "no tool outside the billing job")
check(not (set(CUSTOMER_REFUSALS) & set(QUEUE_REASONS)), "a reason is either told to the customer or queued, never both")
check(QUEUE_REASONS == {"over_cap"}, "only the cap goes to a person")

# the record: construction
check(rec().to_dict()["steps"] == [], "new record has no steps")
check(raises(ValueError, CaseRecord, "case_x", CUST), "case id must be server-made")
check(raises(ValueError, CaseRecord, CASE, "cust_1"), "short customer id")
check(raises(ValueError, CaseRecord, CASE, "cust_001\n"), "customer id with a trailing newline")
check(raises(ValueError, CaseRecord, CASE, "cust_١٢٣"), "non-ASCII digits in the customer id")
check(raises(ValueError, CaseRecord, CASE, CUST, "", 0), "zero steps allowed is refused")
check(raises(ValueError, CaseRecord, CASE, CUST, "", True), "max_steps as a bool is refused")

# the record: steps and the limit
r = rec()
s = r.add_step("get_order", "ok")
check(s == {"n": 1, "tool": "get_order", "mode": "", "status": "ok", "reason": ""}, "first step is numbered 1")
r.add_step("issue_refund", "preview", mode="dry_run")
r.add_step("issue_refund", "refused", reason="over_cap", mode="commit")
check([x["n"] for x in r.steps] == [1, 2, 3], "steps are numbered in order")
check(raises(ValueError, r.add_step, "get_order", "ok", reason="Over the cap!"), "free text as a reason")
check(raises(ValueError, r.add_step, "get_order", "ok", reason="over cap"), "a space in a reason")
check(raises(ValueError, r.add_step, "cancel_subscription", "ok"), "a tool outside the list")
check(raises(ValueError, r.add_step, "request_refund", "ok"), "the model-side name is not a step")
check(raises(ValueError, r.add_step, "get_order", "maybe"), "unknown status")
check(raises(ValueError, r.add_step, "get_order", "ok", mode="later"), "unknown mode")
check(len(r.steps) == 3, "refused steps are not recorded")

lim = rec(max_steps=3)
for _ in range(3):
    lim.add_step("search_policy", "ok")
check(raises(StepLimitReached, lim.add_step, "search_policy", "ok"), "the fourth step is past the limit")
check(len(lim.steps) == 3, "the step past the limit is not recorded")
check(MAX_STEPS == 8, "default limit is 8 steps")

# the record: finishing
f = rec()
f.finish("settled")
check(f.outcome == "settled" and f.reason == "" and f.item_id is None, "settled needs no reason")
check(raises(ValueError, f.finish, "settled"), "a case finishes once")
check(raises(ValueError, f.add_step, "get_order", "ok"), "no steps after the end")
check(raises(ValueError, rec().finish, "queued", "over_cap"), "queued needs an item id")
check(raises(ValueError, rec().finish, "settled", "", "item-1"), "settled has no item")
check(raises(ValueError, rec().finish, "refused"), "refused needs a reason")
check(raises(ValueError, rec().finish, "needs_person"), "needs_person needs a reason")
check(raises(ValueError, rec().finish, "approved"), "unknown outcome")
check(raises(ValueError, rec().finish, "refused", "no clause was given"), "free text as the outcome reason")
q = rec()
q.finish("queued", "over_cap", 17)
check(q.item_id == "17" and q.outcome == "queued", "queued keeps its item id as text")
check(set(OUTCOMES) == {"settled", "queued", "refused", "needs_person"}, "four outcomes")

# what may go to a trace and what is in the record
d = q.to_dict()
check(set(d) == {"case_id", "customer_id", "intent", "steps", "outcome", "reason", "item_id", "error"}, "record fields are fixed")
check("token" not in str(d).lower() and "message" not in str(d).lower(), "no token and no message text in the record")
check(q.trace_fields() == {"billing_outcome": "queued", "billing_reason": "over_cap", "billing_steps": 0, "billing_queued": True,
                           "billing_error": ""}, "trace fields are labels and counts")
check("amount" not in str(q.trace_fields()) and "customer" not in str(q.trace_fields()), "no amount and no customer id in a trace")
d["steps"].append({"n": 9})
check(q.steps == [], "to_dict returns a copy")

# the budget check, before a tool runs
b = rec(max_steps=3)
b.check_budget(2)
b.add_step("get_order", "ok")
b.add_step("get_order", "ok")
check(raises(StepLimitReached, b.check_budget, 2), "two steps do not fit when one is left")
b.check_budget(1)
check(len(b.steps) == 2, "a budget check records nothing")
check("close_case" in MODEL_TOOLS and "close_case" not in STEP_TOOLS, "close_case is a model tool and is not a tool call that ran")

# an error name on the record
e = rec()
e.finish("needs_person", "tool_error", error="TimeoutError")
check(e.error == "TimeoutError" and e.to_dict()["error"] == "TimeoutError" and e.trace_fields()["billing_error"] == "TimeoutError", "an exception class name is kept")
check(raises(ValueError, rec().finish, "needs_person", "tool_error", None, "connection refused for cust_001"), "an error message is not kept")
check(raises(ValueError, rec().finish, "needs_person", "tool_error", None, "Error: 1"), "punctuation is not a class name")

# how the model may close a case
check(close_case_problems({"outcome": "refused", "reason": "not_eligible"}) == [], "refused with not_eligible")
for why in AGENT_CLOSES["needs_person"]:
    check(close_case_problems({"outcome": "needs_person", "reason": why}) == [], f"needs_person with {why}")
check(close_case_problems({"outcome": "settled", "reason": ""}) != [], "the model cannot close a case as settled")
check(close_case_problems({"outcome": "queued", "reason": "over_cap"}) != [], "the model cannot close a case as queued")
check(close_case_problems({"outcome": "refused", "reason": "missing_details"}) != [], "a reason that belongs to another outcome")
check(close_case_problems({"outcome": "refused", "reason": "Not eligible, sorry"}) != [], "free text as a reason")
check(close_case_problems({"outcome": "refused", "reason": "not_eligible", "note": "hi"}) != [], "an extra argument")
check(close_case_problems({"outcome": "refused"}) != [], "reason missing")
check(close_case_problems("refused") != [], "not an object")

# the model's arguments
check(refund_args_problems(args()) == [], "plain refund request is fine")
check(refund_args_problems(args(clause_doc=None, clause_id=None)) == [], "a missing clause reaches the server, which refuses and logs it")
check(refund_args_problems(args(amount="19")) == [], "whole amount")
check(refund_args_problems("refund") != [], "not an object")
check(refund_args_problems({"order_id": "ord_1042"}) != [], "amount missing")
check(refund_args_problems({"amount": "5.00"}) != [], "order id missing")
check(any(f == "customer_id" for f, _ in refund_args_problems({**args(), "customer_id": "cust_002"})), "the model may not choose the customer")
check(any(f == "dry_run" for f, _ in refund_args_problems({**args(), "dry_run": False})), "the model may not turn off the dry run")
check(any(f == "confirm_token" for f, _ in refund_args_problems({**args(), "confirm_token": "abc"})), "the model may not hold a token")
check(refund_args_problems(args(order_id="ord_12")) != [], "short order id")
check(refund_args_problems(args(order_id="ord_1042\n")) != [], "trailing newline in the order id")
check(refund_args_problems(args(order_id="ord_١٠٤٢")) != [], "non-ASCII digits in the order id")
check(refund_args_problems(args(amount="-5")) != [], "negative amount")
check(refund_args_problems(args(amount="1e3")) != [], "exponent in the amount")
check(refund_args_problems(args(amount="19.999")) != [], "three decimals")
check(refund_args_problems(args(amount=19)) != [], "amount as a number")
check(refund_args_problems(args(amount="19.00\n")) != [], "trailing newline in the amount")
check(refund_args_problems(args(clause_doc="TOS v3; drop table")) != [], "SQL-looking text as a document")
check(refund_args_problems(args(clause_id="2.2 and more")) != [], "free text as a clause")
check(refund_args_problems(args(clause_id=22)) != [], "clause as a number")

# after the dry run
check(next_after_dry_run({"status": "preview", "token": "t0k"}) == ("commit", ""), "a preview with a token goes on to the commit")
check(next_after_dry_run({"status": "preview"}) == ("needs_person", "unexpected_result"), "a preview with no token is not acted on")
check(next_after_dry_run({"status": "preview", "token": ""}) == ("needs_person", "unexpected_result"), "an empty token is not acted on")
check(next_after_dry_run({"status": "refused", "reason": "over_cap"}) == ("queue", "over_cap"), "over the cap goes to the queue")
for why in sorted(CUSTOMER_REFUSALS):
    check(next_after_dry_run({"status": "refused", "reason": why}) == ("refused", why), f"{why} is told to the customer")
for why in ("token_invalid", "token_used", "internal_error", "request_already_open"):
    check(next_after_dry_run({"status": "refused", "reason": why}) == ("needs_person", why), f"{why} is a fault, a person looks")
check(next_after_dry_run({"status": "done"}) == ("needs_person", "unexpected_result"), "done at the dry run is unexpected")
check(next_after_dry_run({"status": "refused", "reason": "Not allowed, sorry"}) == ("needs_person", "unexpected_result"), "a free-text reason is not trusted")
check(next_after_dry_run({"status": "refused"}) == ("needs_person", "unexpected_result"), "a refusal with no reason")
check(next_after_dry_run(None) == ("needs_person", "unexpected_result"), "no result")
check(next_after_dry_run("preview") == ("needs_person", "unexpected_result"), "a result that is not an object")

# after the commit
check(outcome_after_commit({"status": "done", "refund_id": "r1"}) == ("settled", ""), "done with a refund id is settled")
check(outcome_after_commit({"status": "done"}) == ("needs_person", "unexpected_result"), "done with no refund id is not trusted")
check(outcome_after_commit({"status": "refused", "reason": "over_cap"}) == ("queued", "over_cap"), "a cap that filled up is queued")
check(outcome_after_commit({"status": "refused", "reason": "over_refundable"}) == ("refused", "over_refundable"), "over the order amount is refused")
check(outcome_after_commit({"status": "refused", "reason": "token_expired"}) == ("needs_person", "token_expired"), "an expired token is a fault, a person looks")
check(outcome_after_commit({"status": "preview", "token": "x"}) == ("needs_person", "unexpected_result"), "a preview at the commit is unexpected")
check(outcome_after_commit({}) == ("needs_person", "unexpected_result"), "an empty result")

# the proposal for the queue
p = refund_proposal(CASE, CUST, "please refund my order", args())
check(p["tool"] == "issue_refund", "the proposal names the tool a person would run")
check(p["args"] == {"customer_id": CUST, "order_id": "ord_1042", "amount": "19.00", "clause_doc": "tos_v3", "clause_id": "2.2"},
      "the proposal holds exactly what would be refunded")
check("dry_run" not in p["args"] and "confirm_token" not in p["args"], "no token and no dry run flag in a proposal")
check(p["summary"] == "Refund request over the cap: a person decides whether to refund 19.00 on order ord_1042.", "summary is fixed words")
check(p["case_id"] == CASE and p["question"] == "please refund my order", "case id and question are passed on")
check(raises(ValueError, refund_proposal, CASE, CUST, "q", args(order_id="bad")), "an invalid request cannot be proposed")
check(raises(ValueError, refund_proposal, CASE, "cust_x", "q", args()), "an invalid customer cannot be proposed")
check(raises(ValueError, refund_proposal, "case_x", CUST, "q", args()), "an invalid case id cannot be proposed")
check(raises(ValueError, refund_proposal, CASE, CUST, "q", {**args(), "customer_id": "cust_002"}), "the model's customer id is not accepted")

print(f"BILLING LOGIC TESTS: {n} checks passed")
