"""Tests for the triage scorer. No model, no network."""
import json

from triage_scoring import score_row, summarize

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


def row(intent="refund", owner="billing", facts=None, cat="clear", id="T00"):
    return {"id": id, "expected_intent": intent, "expected_specialist": owner,
            "expected_facts": json.dumps(facts or {}), "category": cat}


def got(intent="refund", fallback=False, **facts):
    base = {"intent": intent, "order_id": None, "amount": None, "currency": None,
            "days_since_purchase": None, "fallback": fallback}
    base.update(facts)
    return base


s = score_row(row(), got())
check(s["passed"] and s["flags"] == [], "a correct row passes")
s = score_row(row(facts={"order_id": "ord_1042"}), got(order_id="ord_1042"))
check(s["passed"], "a correct fact passes")

s = score_row(row("policy_question", "none"), got("refund"))
check("false_route" in s["flags"] and not s["passed"], "a question sent to billing is a false route")
s = score_row(row(), got("policy_question"))
check("missed_route" in s["flags"] and not s["passed"], "a request treated as a question is a missed route")
s = score_row(row("privacy", "privacy"), got("refund"))
check("wrong_owner" in s["flags"], "the wrong specialist is flagged")
check("false_route" not in s["flags"] and "missed_route" not in s["flags"], "wrong owner is not also a false or missed route")

s = score_row(row(), got(amount="5000"))
check("invented_fact" in s["flags"] and s["invented"] == ["amount"], "an unstated fact is invented")
s = score_row(row(facts={"amount": "19"}), got(amount="19.00"))
check("invented_fact" in s["flags"], "a fact with another value is invented")
s = score_row(row(facts={"order_id": "ord_1042"}), got())
check("missing_fact" in s["flags"] and s["missing"] == ["order_id"] and not s["passed"], "a left-out fact is missing")
s = score_row(row("policy_question", "none"), got("policy_question", fallback=True))
check("fallback" in s["flags"] and not s["passed"], "a fallback row never passes, even with the right intent")
check(s["intent_ok"] is False, "and a fallback never counts as a correct intent, even by luck")

rows = [score_row(row(id=f"T{i}"), got()) for i in range(10)]
r = summarize(rows)
check(r["gate_ok"] and r["intent_accuracy"] == 1.0 and r["passed"] == 10, "ten correct rows pass the gate")

rows[0] = score_row(row("policy_question", "none", id="T0"), got("refund"))
r = summarize(rows)
check(not r["gate_ok"] and r["flags"]["false_route"] == 1, "one false route fails the gate")

rows = [score_row(row(id=f"T{i}"), got()) for i in range(10)]
rows[0] = score_row(row(id="T0"), got(amount="5000"))
check(not summarize(rows)["gate_ok"], "one invented fact fails the gate")

rows = [score_row(row(id=f"T{i}"), got()) for i in range(10)]
rows[0] = score_row(row("privacy", "privacy", id="T0"), got("account"))
rows[1] = score_row(row("privacy", "privacy", id="T1"), got("account"))
r = summarize(rows)
check(r["intent_accuracy"] == 0.8 and not r["gate_ok"], "80% accuracy fails the 90% floor")

rows = [score_row(row(id=f"T{i}"), got()) for i in range(10)]
rows.append(score_row(row("refund", "billing", cat="multi", id="M1"), got("subscription")))
r = summarize(rows)
check(r["gate_ok"] and r["multi_rows"] == 1 and r["multi_passed"] == 0 and r["rows"] == 10, "a wrong multi row is reported apart and does not gate")
check(not summarize([])["gate_ok"], "an empty run never passes")

print(f"TRIAGE SCORING TESTS: {n} checks passed")
