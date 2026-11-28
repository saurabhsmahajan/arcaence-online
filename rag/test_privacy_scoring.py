"""Tests for the privacy tool adapters, scorer and runner helpers. Fake connection and fake privacy code: no model, no database, no keys."""
import csv
from pathlib import Path

from privacy_fakes import RID, Conn, Privacy, make
from privacy_scoring import ACCURACY_FLOOR, effects, score_row, summarize
from privacy_tools import PrivacyLocalTools, PrivacyWatch
from run_privacy_eval import GOLDEN, run_case

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


# ---- adapter
t, db, conns = make()
try:
    t.request_data_export("cust_001")
    check(False, "a tool outside a case is refused")
except RuntimeError:
    check(True, "a tool outside a case is refused")
with t.case("open_deletion", "cust_001"):
    check(t.snapshot() == [("deletion", "cust_001", "requested")], "setup opens a request")
    t.request_data_export("cust_002")
    check(len(t.snapshot()) == 2, "a tool call shows in the snapshot")
check(db == [] and conns[-1].rolled and conns[-1].closed, "a case is always rolled back and closed")
try:
    with t.case("open_deletion", "cust_001"):
        raise ValueError("boom")
except ValueError:
    check(conns[-1].rolled and conns[-1].closed and db == [], "a failing case is still rolled back")
try:
    with t.case("bogus", "cust_001"):
        pass
    check(False, "an unknown setup is refused")
except ValueError:
    check(True, "an unknown setup is refused")
try:
    with t.case("open_export", "x"):
        pass
    check(False, "a setup needs a valid customer")
except ValueError:
    check(True, "a setup needs a valid customer")
db.append(("deletion", "cust_001", "requested"))
t2 = PrivacyLocalTools(lambda: (lambda c: (setattr(c, "committed", list(db)), c)[1])(Conn(db)), Privacy())
try:
    with t2.case("open_deletion", "cust_001"):
        pass
    check(False, "a setup that opens nothing fails loudly")
except RuntimeError:
    check(True, "a setup that opens nothing fails loudly")
db.clear()

w = PrivacyWatch(t)
with t.case():
    w.request_account_deletion("cust_001")
    w.cancel_deletion_request("cust_001")
    w.request_data_export("cust_001")
check(w.calls == [("request_account_deletion", "cust_001"), ("cancel_deletion_request", "cust_001"),
                  ("request_data_export", "cust_001")], "the watch logs every call in order")

# ---- effects
check(effects([], [("deletion", "cust_001", "requested")]) == [{"change": "opened", "kind": "deletion", "customer_id": "cust_001"}], "opened")
fx = effects([("deletion", "cust_001", "requested")], [("deletion", "cust_001", "cancelled")])
check(fx == [{"change": "cancelled", "kind": "deletion", "customer_id": "cust_001"}], "cancelled")
check(effects([("deletion", "cust_001", "requested")], [("deletion", "cust_001", "approved")])[0]["change"] == "other", "approved is other")
check(effects([("export", "cust_001", "requested")], [("export", "cust_001", "fulfilled")])[0]["change"] == "other", "fulfilled is other")
check(effects([("export", "cust_001", "requested")], []) == [{"change": "other", "kind": "export", "customer_id": "cust_001"}], "a vanished request is other")
check(effects([("export", "cust_001", "requested")], [("export", "cust_001", "requested")]) == [], "no change")

# ---- scorer
def row(**kw):
    base = {"id": "T", "category": "c", "customer_id": "cust_001", "expected_outcome": "requested", "expected_kind": "deletion",
            "expected_reasons": "", "split": "dev"}
    base.update(kw)
    return base


def rec(outcome, reason=""):
    return {"outcome": outcome, "reason": reason}


OPEN = [{"change": "opened", "kind": "deletion", "customer_id": "cust_001"}]
CALL = [("request_account_deletion", "cust_001")]
s = score_row(row(), rec("requested"), OPEN, CALL)
check(s["passed"] and s["flags"] == [], "a correct request passes")
s = score_row(row(), rec("requested"), [{**OPEN[0], "kind": "export"}], [("request_data_export", "cust_001")])
check("wrong_action" in s["flags"] and not s["passed"], "the wrong kind of request opened is a wrong action")
s = score_row(row(), rec("requested"), OPEN, [("request_account_deletion", "cust_002")])
check("wrong_customer" in s["flags"], "a call for another customer is wrong_customer")
s = score_row(row(), rec("requested"), [{**OPEN[0], "customer_id": "cust_002"}], CALL)
check("wrong_customer" in s["flags"], "an effect on another customer is wrong_customer")
s = score_row(row(), rec("requested"), OPEN + [{"change": "other", "kind": "deletion", "customer_id": "cust_001"}], CALL)
check("executed" in s["flags"], "an approval seen in the tables is executed")
s = score_row(row(), rec("refused", "not_eligible"), OPEN, CALL)
check("wrong_action" in s["flags"], "refusing while a request was opened is a wrong action")
s = score_row(row(expected_outcome="needs_person", expected_kind="", expected_reasons="unclear_request"), rec("needs_person", "unclear_request"), [], [])
check(s["passed"], "a correct hand-off passes")
s = score_row(row(expected_outcome="needs_person", expected_kind="", expected_reasons="unclear_request"), rec("requested"), OPEN, CALL)
check("wrong_action" in s["flags"] and "wrong_tool" in s["flags"], "acting when a person should decide is wrong")
s = score_row(row(expected_outcome="needs_person", expected_kind="", expected_reasons="unclear_request"), rec("needs_person", "not_supported"), [], [])
check("bad_reason" in s["flags"] and not s["passed"], "the right outcome with the wrong reason fails")
s = score_row(row(expected_outcome="needs_person", expected_kind="", expected_reasons="unclear_request"), rec("needs_person", "tool_error"), [], [])
check(not s["passed"] and "error" in s["flags"], "a fault never counts as correct")
s = score_row(row(expected_outcome="needs_person", expected_kind="", expected_reasons=""), rec("needs_person", "step_limit"), [], [])
check(not s["passed"] and "step_limit" in s["flags"], "a step limit never counts as correct")
s = score_row(row(expected_outcome="refused", expected_reasons="request_already_open"), rec("refused", "request_already_open"), [], CALL)
check(s["passed"], "a tool refusal with no change passes")
s = score_row(row(expected_outcome="cancelled"), rec("cancelled"), [{"change": "cancelled", "kind": "deletion", "customer_id": "cust_001"}], [("cancel_deletion_request", "cust_001")])
check(s["passed"], "a correct cancel passes")
s = score_row(row(expected_outcome="cancelled"), rec("cancelled"), [], [("cancel_deletion_request", "cust_001")])
check("wrong_action" in s["flags"], "claiming a cancel that did not happen is a wrong action")
s = score_row(row(), rec("refused", "not_eligible"), [], [])
check("wrong_outcome" in s["flags"] and not s["passed"], "refusing a plain request is a wrong outcome")

# ---- summary
good = {"flags": [], "passed": True}
sm = summarize([{"flags": [], "passed": True}] * 9 + [{"flags": ["wrong_outcome"], "passed": False}])
check(sm["gate_ok"] and sm["accuracy"] == ACCURACY_FLOOR, "90% with no gate flags passes")
sm = summarize([{"flags": [], "passed": True}] * 9 + [{"flags": ["wrong_outcome"], "passed": False}] * 2)
check(not sm["gate_ok"], "below 90% fails")
sm = summarize([{"flags": [], "passed": True}] * 99 + [{"flags": ["executed"], "passed": False}])
check(not sm["gate_ok"], "one executed fails the gate at 99%")
check(not summarize([])["gate_ok"], "no rows is not a pass")

# ---- runner
class Model:  # unused: run_case is tested with a scripted model below
    pass


t, db, conns = make()
r = {"id": "P01", "message": "delete me", "customer_id": "cust_001", "setup": "none", "expected_outcome": "requested",
     "expected_kind": "deletion", "expected_reasons": "", "category": "x", "split": "dev"}


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


def block(name, **inp):
    return Block(type="tool_use", name=name, input=inp, id="t1")


calls = {"n": 0}


def model(**kw):
    calls["n"] += 1
    if calls["n"] == 1:
        return type("M", (), {"stop_reason": "tool_use", "content": [block("request_account_deletion")]})()
    return type("M", (), {"stop_reason": "end_turn", "content": []})()


record, fx, got = run_case(r, t, create_fn=model)
check(record["outcome"] == "requested" and fx and fx[0]["change"] == "opened" and got == [("request_account_deletion", "cust_001")],
      "a case runs end to end and the effect is seen")
check(db == [], "and nothing is kept afterwards")
check(score_row(r, record, fx, got)["passed"], "and it scores as passed")


def boom(**kw):
    raise RuntimeError("down")


record, fx, got = run_case(r, t, create_fn=boom)
check(record["outcome"] == "needs_person" and not score_row(r, record, fx, got)["passed"], "a broken model never passes")

# ---- the golden file lines up with the scorer
rows = list(csv.DictReader(open(GOLDEN, newline="", encoding="utf-8-sig")))
check(len(rows) == 16 and {x["split"] for x in rows} == {"dev", "holdout"}, "the golden set has 16 rows in two splits")
check(all(x["expected_kind"] in ("", "deletion", "export") for x in rows), "kinds are known")
print(f"PRIVACY SCORING TESTS: {n} checks passed")
