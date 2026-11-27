"""Tests for the part of the billing agent that code runs. Fake tools, no model, no database, no keys."""
from billing_flow import close_case, settle_refund
from billing_logic import CaseRecord

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


CASE = "case_20261127_0123456789ab"
CUST = "cust_001"
TOKEN = "s3cret-token-value"


class FakeTools:
    """Returns scripted results in order and logs every call. A result that is an Exception is raised."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def issue_refund(self, **kw):
        self.calls.append(kw)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeQueue:
    def __init__(self, item_id=17, fail=None):
        self.item_id, self.fail, self.items = item_id, fail, []

    def __call__(self, proposal):
        if self.fail:
            raise self.fail
        self.items.append(proposal)
        return self.item_id


def rec(**kw):
    return CaseRecord(CASE, CUST, **kw)


def args(**kw):
    base = {"order_id": "ord_1001", "amount": "19.00", "clause_doc": "tos_v3", "clause_id": "3.3"}
    base.update(kw)
    return base


PREVIEW = {"status": "preview", "token": TOKEN, "expires_at": "x", "refund": {}, "cap_remaining_after": "31.00"}
DONE = {"status": "done", "refund_id": "r-1", "order_id": "ord_1001", "amount": "19.00", "currency": "EUR"}


def refused(reason):
    return {"status": "refused", "reason": reason}


# --- the refund goes through -------------------------------------------------------------------------------
t, q, r = FakeTools(PREVIEW, DONE), FakeQueue(), rec()
out = settle_refund(t, r, args(), "please refund", q)
check(out == {"status": "closed", "outcome": "settled", "reason": ""}, "a refund inside the cap is settled")
check(len(t.calls) == 2, "two calls: the dry run and the commit")
check(t.calls[0]["dry_run"] is True and t.calls[0]["confirm_token"] is None, "the first call is a dry run with no token")
check(t.calls[1]["dry_run"] is False and t.calls[1]["confirm_token"] == TOKEN, "the second call commits with the token")
check(all(c["customer_id"] == CUST for c in t.calls), "the customer id comes from the case record")
check([(s["status"], s["mode"]) for s in r.steps] == [("preview", "dry_run"), ("done", "commit")], "both calls are recorded")
check(TOKEN not in str(r.to_dict()) and TOKEN not in str(out), "the token is in neither the record nor the result")
check(q.items == [], "nothing is queued")
check(r.outcome == "settled" and r.item_id is None, "the record is finished as settled")

# --- over the cap: the human gate ---------------------------------------------------------------------------
t, q, r = FakeTools(refused("over_cap")), FakeQueue(17), rec()
out = settle_refund(t, r, args(order_id="ord_2001", amount="540.00"), "full refund please", q)
check(out == {"status": "closed", "outcome": "queued", "reason": "over_cap"}, "over the cap is queued")
check(len(t.calls) == 1, "no commit is attempted")
check(len(q.items) == 1, "one item is queued")
p = q.items[0]
check(p["tool"] == "issue_refund" and p["case_id"] == CASE and p["question"] == "full refund please", "the proposal names the tool, the case and the question")
check(p["args"] == {"customer_id": CUST, "order_id": "ord_2001", "amount": "540.00", "clause_doc": "tos_v3", "clause_id": "3.3"}, "the proposal holds exactly what would run")
check("token" not in str(p) and "dry_run" not in str(p["args"]), "no token and no dry run flag in the proposal")
check(r.outcome == "queued" and r.reason == "over_cap" and r.item_id == "17", "the record keeps the queue item id")

t, q, r = FakeTools(PREVIEW, refused("over_cap")), FakeQueue(18), rec()
out = settle_refund(t, r, args(), "refund", q)
check(out["outcome"] == "queued" and len(q.items) == 1 and len(t.calls) == 2, "a cap that filled up before the commit is queued")
check(r.item_id == "18", "its item id is kept")

# --- refusals the customer is told about --------------------------------------------------------------------
for why in ("wrong_customer", "order_not_found", "over_refundable", "clause_not_allowed", "no_clause", "invalid_amount"):
    t, q, r = FakeTools(refused(why)), FakeQueue(), rec()
    out = settle_refund(t, r, args(), "refund", q)
    check(out == {"status": "closed", "outcome": "refused", "reason": why}, f"{why} is refused")
    check(len(t.calls) == 1 and q.items == [], f"{why}: no commit and no queue item")

# --- faults: a person looks ---------------------------------------------------------------------------------
for why in ("token_expired", "token_used", "internal_error", "args_mismatch"):
    t, q, r = FakeTools(PREVIEW, refused(why)), FakeQueue(), rec()
    out = settle_refund(t, r, args(), "refund", q)
    check(out == {"status": "closed", "outcome": "needs_person", "reason": why}, f"{why} at the commit goes to a person")
    check(q.items == [], f"{why}: nothing is queued")

t, q, r = FakeTools({"status": "weird"}), FakeQueue(), rec()
check(settle_refund(t, r, args(), "refund", q)["reason"] == "unexpected_result", "an unexpected result goes to a person")
check(r.steps[0]["status"] == "error", "and is recorded as an error step")
t, q, r = FakeTools({"status": "preview"}), FakeQueue(), rec()
out = settle_refund(t, r, args(), "refund", q)
check(out["outcome"] == "needs_person" and len(t.calls) == 1, "a preview with no token is not committed")

# --- exceptions ---------------------------------------------------------------------------------------------
t, q, r = FakeTools(TimeoutError("db slow for cust_001")), FakeQueue(), rec()
out = settle_refund(t, r, args(), "refund", q)
check(out == {"status": "closed", "outcome": "needs_person", "reason": "tool_error"}, "a tool that raises at the dry run goes to a person")
check(r.error == "TimeoutError" and "db slow" not in str(r.to_dict()), "only the class name is kept, never the message")
check(r.steps[0]["status"] == "error" and r.steps[0]["mode"] == "dry_run", "the failed call is recorded")

t, q, r = FakeTools(PREVIEW, ConnectionError("lost")), FakeQueue(), rec()
out = settle_refund(t, r, args(), "refund", q)
check(out == {"status": "closed", "outcome": "needs_person", "reason": "commit_unclear"}, "a commit that raises is unclear, not refused and not settled")
check(r.error == "ConnectionError" and r.steps[1]["mode"] == "commit" and r.steps[1]["status"] == "error", "the commit is recorded as an error")
check(q.items == [], "an unclear commit is not queued")

# --- the honesty rule for the queue -------------------------------------------------------------------------
t, q, r = FakeTools(refused("over_cap")), FakeQueue(fail=RuntimeError("queue down")), rec()
out = settle_refund(t, r, args(), "refund", q)
check(out == {"status": "closed", "outcome": "needs_person", "reason": "queue_failed"}, "a failed queue write is never reported as queued")
check(r.item_id is None and r.error == "RuntimeError", "no item id, and the error class is kept")
t, q, r = FakeTools(refused("over_cap")), FakeQueue(item_id=None), rec()
check(settle_refund(t, r, args(), "refund", q)["reason"] == "queue_failed", "a queue that returns no item id is a failure")

# --- the step limit -----------------------------------------------------------------------------------------
t, q, r = FakeTools(PREVIEW, DONE), FakeQueue(), rec(max_steps=1)
out = settle_refund(t, r, args(), "refund", q)
check(out == {"status": "closed", "outcome": "needs_person", "reason": "step_limit"}, "a refund that cannot finish is not started")
check(t.calls == [], "no tool ran, so no dry run was left without a commit")
t, q, r = FakeTools(PREVIEW, DONE), FakeQueue(), rec(max_steps=2)
check(settle_refund(t, r, args(), "refund", q)["outcome"] == "settled", "exactly two steps are enough")
r = rec(max_steps=3)
r.add_step("get_order", "ok")
r.add_step("search_policy", "ok")
t = FakeTools(PREVIEW, DONE)
check(settle_refund(t, r, args(), "refund", FakeQueue())["reason"] == "step_limit" and t.calls == [], "earlier steps count against the budget")

# --- arguments the model may not give -----------------------------------------------------------------------
for bad, why in (({**args(), "customer_id": "cust_002"}, "customer id"), ({**args(), "dry_run": False}, "dry run flag"),
                 ({**args(), "confirm_token": "abc"}, "token"), (args(amount="-5"), "negative amount"),
                 (args(order_id="ord_1\n"), "bad order id"), ("refund", "not an object")):
    t, q, r = FakeTools(PREVIEW, DONE), FakeQueue(), rec()
    out = settle_refund(t, r, bad, "refund", q)
    check(out["status"] == "rejected" and out["problems"], f"{why} is rejected")
    check(t.calls == [] and r.steps == [] and r.outcome == "", f"{why}: nothing ran and the case is still open")
out = settle_refund(FakeTools(), rec(), {**args(), "customer_id": "cust_002"}, "refund", FakeQueue())
check(out["problems"] == ["customer_id"], "the rejection names the field, never its value")

# --- one ending per case ------------------------------------------------------------------------------------
t, q, r = FakeTools(PREVIEW, DONE), FakeQueue(), rec()
settle_refund(t, r, args(), "refund", q)
try:
    settle_refund(FakeTools(PREVIEW, DONE), r, args(), "refund", q)
    check(False, "a second refund on a finished case")
except ValueError:
    check(True, "a finished case cannot be settled again")

# --- close_case ---------------------------------------------------------------------------------------------
r = rec()
out = close_case(r, {"outcome": "refused", "reason": "not_eligible"})
check(out == {"status": "closed", "outcome": "refused", "reason": "not_eligible"} and r.outcome == "refused", "the model can refuse as not_eligible")
r = rec()
out = close_case(r, {"outcome": "needs_person", "reason": "needs_evidence"})
check(out["outcome"] == "needs_person" and r.reason == "needs_evidence", "the model can send a case to a person")
for bad in ({"outcome": "settled", "reason": ""}, {"outcome": "queued", "reason": "over_cap"},
            {"outcome": "refused", "reason": "missing_details"}, {"outcome": "refused", "reason": "no"},
            {"outcome": "refused", "reason": "not_eligible", "refund": "19.00"}, "refused"):
    r = rec()
    out = close_case(r, bad)
    check(out["status"] == "rejected" and r.outcome == "", f"close_case refuses {bad!r}"[:60])
r = rec()
close_case(r, {"outcome": "refused", "reason": "not_eligible"})
try:
    close_case(r, {"outcome": "refused", "reason": "not_eligible"})
    check(False, "closing twice")
except ValueError:
    check(True, "a case closes once")

print(f"BILLING FLOW TESTS: {n} checks passed")
