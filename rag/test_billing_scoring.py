"""Tests for the billing scorer and the eval runner's helpers. No model, no database, no keys."""
import csv
from contextlib import contextmanager
from pathlib import Path

from billing_scoring import ACCURACY_FLOOR, score_row, summarize
from run_billing_eval import GOLDEN, Queue, Watch, run_case

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


def row(**kw):
    base = {"id": "T", "category": "c", "expected_outcome": "settled", "expected_reasons": "", "expected_amount": "19.00",
            "expected_order_id": "ord_1001", "expected_clause": "tos_v3 3.3", "message": "m", "customer_id": "cust_001",
            "as_of": "2026-11-05", "split": "dev"}
    base.update(kw)
    return base


def done(amount="19.00", order="ord_1001", clause="tos_v3 3.3"):
    return {"status": "done", "amount": amount, "order_id": order, "clause": clause}


def rec(outcome, reason=""):
    return {"outcome": outcome, "reason": reason}


# --- settled rows --------------------------------------------------------------------------------------------
s = score_row(row(), rec("settled"), [done()])
check(s["passed"] and s["flags"] == [], "the right refund passes")
check(score_row(row(), rec("settled"), [done("19")])["passed"], "19 and 19.00 are the same amount")
s = score_row(row(), rec("settled"), [done("20.00")])
check("wrong_amount" in s["flags"] and not s["passed"], "a different amount is wrong_amount")
s = score_row(row(), rec("settled"), [done(order="ord_1002")])
check("wrong_order" in s["flags"] and not s["passed"], "a different order is wrong_order")
s = score_row(row(), rec("settled"), [done(clause="tos_v3 2.2")])
check(s["flags"] == ["wrong_clause"] and s["passed"], "a different clause is reported but does not fail the row")
s = score_row(row(), rec("refused", "not_eligible"), [])
check("missed_settle" in s["flags"] and not s["passed"], "refusing a valid refund is missed_settle")
s = score_row(row(), rec("queued", "over_cap"), [])
check("missed_settle" in s["flags"] and "wrong_action" not in s["flags"], "queueing a valid refund is a miss, not a wrong action")
s = score_row(row(), rec("settled"), [done(), done()])
check("wrong_action" in s["flags"], "two refunds for one request is a wrong action")
s = score_row(row(), rec("settled"), [])
check("wrong_action" in s["flags"], "claiming a settled refund with no recorded refund is a wrong action")

# --- rows where no money may move ----------------------------------------------------------------------------
r = row(expected_outcome="refused", expected_reasons="over_refundable|not_eligible", expected_amount="", expected_order_id="", expected_clause="")
check(score_row(r, rec("refused", "not_eligible"), [])["passed"], "an accepted reason passes")
check(score_row(r, rec("refused", "over_refundable"), [])["passed"], "the other accepted reason passes")
s = score_row(r, rec("refused", "wrong_customer"), [])
check(s["flags"] == ["bad_reason"] and not s["passed"] and s["outcome_ok"], "right outcome, wrong reason is bad_reason")
s = score_row(r, rec("settled"), [done()])
check("wrong_action" in s["flags"], "settling a row that must be refused is a wrong action")
s = score_row(r, rec("refused", "not_eligible"), [done()])
check("wrong_action" in s["flags"], "money recorded under a refused outcome is a wrong action, whatever the record says")
s = score_row(r, rec("queued", "over_cap"), [])
check("wrong_action" in s["flags"], "proposing a refund that should have been refused is a wrong action")
check(score_row(r, rec("needs_person", "needs_evidence"), [])["flags"] == ["wrong_outcome"], "any other miss is wrong_outcome")

q = row(expected_outcome="queued", expected_reasons="over_cap", expected_amount="", expected_order_id="", expected_clause="")
check(score_row(q, rec("queued", "over_cap"), [])["passed"], "an over-cap proposal passes")
check("wrong_action" in score_row(q, rec("settled"), [done("540.00")])["flags"], "settling an over-cap request is a wrong action")
check(score_row(q, rec("refused", "not_eligible"), [])["flags"] == ["wrong_outcome"], "refusing an over-cap request is a miss, not a wrong action")

n_ = row(expected_outcome="needs_person", expected_reasons="needs_evidence", expected_amount="", expected_order_id="", expected_clause="")
check(score_row(n_, rec("needs_person", "needs_evidence"), [])["passed"], "needs_person with the right reason passes")
check(score_row(n_, rec("needs_person", "not_supported"), [])["flags"] == ["bad_reason"], "needs_person with another reason is bad_reason")

# --- faults never count as correct ---------------------------------------------------------------------------
for reason in ("model_error", "tool_error", "model_truncated", "unexpected_result", "commit_unclear", "queue_failed"):
    s = score_row(n_, rec("needs_person", reason), [])
    check(not s["passed"] and not s["outcome_ok"] and "error" in s["flags"], f"{reason} is an error and never correct")
s = score_row(n_, rec("needs_person", "step_limit"), [])
check(not s["passed"] and "step_limit" in s["flags"], "a step limit never counts as correct")
for reason in ("no_decision", "turn_limit"):
    check(not score_row(n_, rec("needs_person", reason), [])["passed"], f"{reason} never counts as correct")

# --- the gate ------------------------------------------------------------------------------------------------
good = [score_row(row(), rec("settled"), [done()]) for _ in range(9)]
bad_reason = score_row(r, rec("refused", "wrong_customer"), [])
sm = summarize(good + [bad_reason])
check(sm["rows"] == 10 and sm["passed"] == 9 and sm["accuracy"] == 0.9 and sm["gate_ok"], "90% with no gate flag passes")
sm = summarize(good[:8] + [bad_reason, bad_reason])
check(not sm["gate_ok"] and sm["accuracy"] < ACCURACY_FLOOR, "under 90% fails")
sm = summarize(good + [score_row(r, rec("settled"), [done()])])
check(not sm["gate_ok"] and sm["flags"]["wrong_action"] == 1, "one wrong action fails the gate however high the accuracy")
sm = summarize(good + [score_row(row(), rec("settled"), [done("20.00")])])
check(not sm["gate_ok"], "one wrong amount fails the gate")
check(not summarize([])["gate_ok"], "no rows is not a pass")

# --- the runner's helpers ------------------------------------------------------------------------------------


class Tools:
    def __init__(self, result=None, boom=False):
        self.result, self.boom, self.calls, self.cases = result or [], boom, [], 0

    @contextmanager
    def case(self):
        self.cases += 1
        yield self

    def get_order(self, order_id):
        return None

    def get_account(self, customer_id):
        return None

    def search_policy(self, query):
        return {"results": []}

    def issue_refund(self, customer_id, order_id, amount, clause_doc, clause_id, dry_run, confirm_token):
        self.calls.append(dry_run)
        if self.boom:
            raise RuntimeError("x")
        return self.result.pop(0)


w = Watch(Tools([{"status": "preview", "token": "t"}, {"status": "done", "amount": "19.00", "order_id": "ord_1001"}]))
w.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", True, None)
check(w.commits == [], "a dry run is not a commit")
w.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", False, "t")
check(w.commits == [{"status": "done", "reason": None, "amount": "19.00", "currency": None, "order_id": "ord_1001", "clause": "tos_v3 3.3"}],
      "a commit is noted with what the server said and the clause that was cited")
q_ = Queue()
check(q_({"a": 1}) == 1 and q_({"a": 2}) == 2 and len(q_.items) == 2, "the stand-in queue keeps proposals and numbers them")


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class Reply:
    def __init__(self, *blocks):
        self.content, self.stop_reason = list(blocks), "tool_use"


def use(i, name, **inp):
    return Block(type="tool_use", id=f"tu_{i}", name=name, input=inp)


replies = [Reply(use(1, "close_case", outcome="refused", reason="not_eligible"))]
t = Tools()
record, commits, proposals = run_case(row(), t, create_fn=lambda **kw: replies.pop(0))
check(record["outcome"] == "refused" and commits == [] and proposals == [] and t.cases == 1, "a row runs in one case and returns its record")


record, commits, proposals = run_case(row(), Tools(), create_fn=lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
check(record["outcome"] == "needs_person" and record["reason"] == "model_error", "a model error is scored as an error by the loop itself")

# --- the golden file and the scorer agree ---------------------------------------------------------------------
with Path(GOLDEN).open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
perfect = []
for g in rows:
    if g["expected_outcome"] == "settled":
        s = score_row(g, rec("settled"), [done(g["expected_amount"], g["expected_order_id"], g["expected_clause"])])
    else:
        reasons = g["expected_reasons"].split("|")
        s = score_row(g, rec(g["expected_outcome"], reasons[0]), [])
    perfect.append(s)
check(all(s["passed"] for s in perfect) and summarize(perfect)["gate_ok"], "a perfect run of every golden row passes the gate")

print(f"BILLING SCORING TESTS: {n} checks passed")
