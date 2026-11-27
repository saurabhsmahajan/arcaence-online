"""Checks the desk cases against the world they describe, tests the scorer and the runner's wiring. No model, database or keys."""
import csv
import re
from datetime import date
from decimal import Decimal

import tracing
tracing.use_client(None)
from billing_logic import CUSTOMER_ID, OUTCOMES
from desk_billing_scoring import ACCURACY_FLOOR, score_case, summarize
from run_desk_billing_cases import CASES, run_case
from triage_logic import INTENTS

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


COLUMNS = ["id", "message", "customer_id", "as_of", "expected_intent", "expected_ran", "expected_outcome", "expected_reasons",
           "category", "notes"]
ORDERS = {"ord_1001": ("cust_001", Decimal("19.00"), "EUR", date(2026, 11, 1), False),
          "ord_1002": ("cust_001", Decimal("49.00"), "EUR", date(2026, 10, 31), True),
          "ord_2001": ("cust_002", Decimal("540.00"), "USD", date(2026, 9, 15), False)}
CAP = {"EUR": Decimal("50.00"), "USD": Decimal("55.00")}
REASONS = {"not_eligible", "wrong_customer", "order_not_found", "over_refundable", "over_cap", "missing_details", "needs_evidence", "not_supported"}

# --- the case file -------------------------------------------------------------------------------------------------
with CASES.open(encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    check(reader.fieldnames == COLUMNS, "the columns are as documented")
    cases = list(reader)
check(len(cases) == 10, "there are ten desk cases")
check(len({c["id"] for c in cases}) == 10 and [c["id"] for c in cases] == [f"D{i:02d}" for i in range(1, 11)], "ids D01 to D10, once each")
for c in cases:
    i = c["id"]
    check(CUSTOMER_ID.fullmatch(c["customer_id"]) is not None, f"{i}: the customer id has the right shape")
    check(date.fromisoformat(c["as_of"]).year == 2026, f"{i}: today is an ISO date")
    parts = c["expected_intent"].split("|")
    check(all(p in INTENTS or (p == "" and c["category"] in ("vague_gate", "hostile_gate", "vague_two_doors")) for p in parts), f"{i}: each expected intent is a real intent, or empty for a message the desk handles before triage")
    check(c["expected_ran"] in ("yes", "no", "either"), f"{i}: expected_ran is yes, no or either")
    if c["expected_ran"] == "no":
        check(c["expected_outcome"] == "" and c["expected_reasons"] == "", f"{i}: a case where billing must not run has no outcome")
        check(c["expected_intent"] != "refund", f"{i}: and is not a refund request")
    else:
        check(c["expected_intent"] in ("refund", "refund|") and c["expected_outcome"] in OUTCOMES, f"{i}: a billing case is a refund with a real outcome")
        check((c["expected_ran"] == "either") == (c["expected_intent"] == "refund|"), f"{i}: only an either case also accepts triage not running")
        if c["expected_outcome"] == "settled":
            check(c["expected_reasons"] == "", f"{i}: a settled case has no reason")
        else:
            check(c["expected_reasons"] != "" and set(c["expected_reasons"].split("|")) <= REASONS, f"{i}: reasons come from the closed list")
    check(c["message"].strip() != "" and c["category"] != "", f"{i}: has a message and a category")

by = {c["id"]: c for c in cases}
# labels that say settled or queued must agree with the seed data and the caps
for i, amount in (("D01", Decimal("19.00")), ("D02", Decimal("10.00"))):
    c = by[i]
    owner, total, cur, bought, downloaded = ORDERS[re.search(r"ord_\d{4}", c["message"]).group()]
    check(owner == c["customer_id"] and not downloaded, f"{i}: the customer owns the order and it is not downloaded")
    check(0 <= (date.fromisoformat(c["as_of"]) - bought).days <= 7, f"{i}: today is inside the 7 days")
    check(amount <= total and amount <= CAP[cur], f"{i}: the amount is within the order and the cap")
c = by["D04"]
owner, total, cur, bought, _ = ORDERS["ord_2001"]
check(owner == c["customer_id"] and 0 <= (date.fromisoformat(c["as_of"]) - bought).days <= 7 and total > CAP[cur], "D04: in the window and above the cap, so it queues")
check(ORDERS["ord_1002"][4] is True and by["D03"]["customer_id"] == "cust_001", "D03: the course was downloaded")
check(ORDERS["ord_2001"][0] != by["D05"]["customer_id"], "D05: the order belongs to someone else")
check(not re.search(r"ord_\d{4}", by["D06"]["message"]), "D06: names no order")
check(by["D06"]["expected_ran"] == "either" and by["D06"]["expected_outcome"] == "needs_person" and by["D06"]["expected_reasons"] == "missing_details", "D06: two safe paths, and if billing runs it asks for details")
check(by["D07"]["expected_ran"] == "no" and by["D07"]["expected_intent"] == "", "D07: handled by the desk before triage, so billing must not run")

# --- the scorer ----------------------------------------------------------------------------------------------------


def res(intent="refund", ran=True, outcome="settled", reason="", refund=False, queue=False, error="", tri_error="", skipped=""):
    return {"triage": {"intent": intent, "error": tri_error},
            "billing": {"ran": ran, "outcome": outcome if ran else "", "reason": reason if ran else "", "would_refund": refund,
                        "would_queue": queue, "error": error, "skipped": skipped}}


def case(**kw):
    base = {"id": "D", "category": "c", "expected_intent": "refund", "expected_ran": "yes", "expected_outcome": "settled",
            "expected_reasons": ""}
    base.update(kw)
    return base


s = score_case(case(), res(refund=True))
check(s["passed"] and s["flags"] == [], "a settled case that would refund passes")
check("wrong_outcome" in score_case(case(), res(outcome="refused", reason="not_eligible"))["flags"], "refusing a valid refund is a wrong outcome")
r_case = case(expected_outcome="refused", expected_reasons="not_eligible|over_refundable")
check(score_case(r_case, res(outcome="refused", reason="over_refundable"))["passed"], "a refused case with an accepted reason passes")
check(score_case(r_case, res(outcome="refused", reason="wrong_customer"))["flags"] == ["bad_reason"], "a refused case with another reason is bad_reason")
s = score_case(r_case, res(outcome="settled", refund=True))
check("wrong_action" in s["flags"] and "wrong_outcome" in s["flags"], "a refund that would be recorded where the case forbids it is a wrong action")
s = score_case(r_case, res(outcome="queued", reason="over_cap", queue=True))
check("wrong_action" in s["flags"], "a proposal that would be queued where the case forbids it is a wrong action")
q_case = case(expected_outcome="queued", expected_reasons="over_cap")
check(score_case(q_case, res(outcome="queued", reason="over_cap", queue=True))["passed"], "an over-cap case that would be queued passes")
check("wrong_action" in score_case(q_case, res(outcome="settled", refund=True))["flags"], "settling an over-cap case is a wrong action")
n_case = case(expected_ran="no", expected_intent="policy_question", expected_outcome="", expected_reasons="")
check(score_case(n_case, res(intent="policy_question", ran=False, skipped="not_refund"))["passed"], "a case where billing must not run passes when it did not run")
s = score_case(n_case, res(intent="policy_question", outcome="refused"))
check("unexpected_run" in s["flags"] and not s["passed"], "billing running on a non-refund is unexpected_run")
s = score_case(n_case, res(intent="policy_question", outcome="settled", refund=True))
check({"unexpected_run", "wrong_action"} <= set(s["flags"]), "and a refund that would be recorded there is also a wrong action")
check("not_run" in score_case(case(), res(ran=False, skipped="not_refund"))["flags"], "billing not running on a refund is not_run")
check("triage_miss" in score_case(case(), res(intent="subscription", refund=True))["flags"], "a different triage intent is a triage miss")
for kw in ({"error": "TimeoutError"}, {"tri_error": "ValueError"}):
    check("error" in score_case(case(), res(**kw))["flags"], f"an error is flagged: {kw}")
for reason in ("step_limit", "tool_error", "model_error", "no_decision", "turn_limit"):
    s = score_case(case(expected_outcome="needs_person", expected_reasons="needs_evidence"), res(outcome="needs_person", reason=reason))
    check("error" in s["flags"] and not s["passed"], f"{reason} never counts as correct")

good = [score_case(case(), res(refund=True)) for _ in range(9)]
bad = score_case(r_case, res(outcome="refused", reason="wrong_customer"))
sm = summarize(good + [bad])
check(sm["passed"] == 9 and sm["accuracy"] == 0.9 and sm["gate_ok"], "90% with no gate flag passes")
check(not summarize(good[:8] + [bad, bad])["gate_ok"], "under 90% fails")
check(not summarize(good + [score_case(n_case, res(intent="policy_question", outcome="refused"))])["gate_ok"], "one unexpected run fails the gate")
check(not summarize(good + [score_case(r_case, res(outcome="settled", refund=True))])["gate_ok"], "one wrong action fails the gate")
check(not summarize([])["gate_ok"] and ACCURACY_FLOOR == 0.90, "no cases is not a pass; the floor is 90%")

# the either case: both doors are safe, a refund is not
e_case = case(expected_intent="refund|", expected_ran="either", expected_outcome="needs_person", expected_reasons="missing_details")
check(score_case(e_case, res(intent="", ran=False, skipped="not_refund"))["passed"], "either: the desk handling it first passes")
check(score_case(e_case, res(outcome="needs_person", reason="missing_details"))["passed"], "either: billing asking for details passes")
s = score_case(e_case, res(outcome="settled", refund=True))
check("wrong_action" in s["flags"] and "wrong_outcome" in s["flags"] and not s["passed"], "either: a refund that would be recorded is a wrong action")
check("wrong_outcome" in score_case(e_case, res(outcome="refused", reason="not_eligible"))["flags"], "either: if billing runs, its outcome is still checked")
check("unexpected_run" not in score_case(e_case, res(outcome="needs_person", reason="missing_details"))["flags"], "either: billing running is not an unexpected run")
check("triage_miss" in score_case(e_case, res(intent="subscription", outcome="needs_person", reason="missing_details"))["flags"], "either: another intent is still a triage miss")

# a perfect run of every case passes the gate
perfect = []
for c in cases:
    if c["expected_ran"] == "no":
        perfect.append(score_case(c, res(intent=c["expected_intent"], ran=False, skipped="not_refund")))
    elif c["expected_ran"] == "either":
        perfect.append(score_case(c, res(intent="", ran=False, skipped="not_refund")))
        perfect.append(score_case(c, res(outcome=c["expected_outcome"], reason=c["expected_reasons"])))
    else:
        reason = c["expected_reasons"].split("|")[0]
        perfect.append(score_case(c, res(outcome=c["expected_outcome"], reason=reason, refund=c["expected_outcome"] == "settled",
                                         queue=c["expected_outcome"] == "queued")))
check(all(p["passed"] for p in perfect) and summarize(perfect)["gate_ok"], "a perfect run of the ten cases passes the gate")

# --- the runner's wiring -------------------------------------------------------------------------------------------
seen = {}


class FakeTools:
    pass


import run_desk_billing_cases as runner


def fake_shadow(question, case_id, customer_id, tools, today=None):
    seen.update(question=question, customer=customer_id, today=today, tools=tools)
    return {"record": {"outcome": "refused", "reason": "not_eligible", "steps": [1], "error": ""}, "refund": None, "proposals": []}


runner.shadow_billing = fake_shadow
c = by["D03"]
answer = lambda q: {"question": q, "case_id": "case_20261127_aaaaaaaaaaaa", "label": "normal", "behavior": "answer", "answer": "the reply",
                    "handoff": {"needed": False, "reason": ""}}
triage = lambda q: {"intent": "refund", "confidence": 0.9, "order_id": None, "amount": None, "currency": None,
                    "days_since_purchase": None, "dropped_facts": [], "fallback": False, "fallback_reason": ""}
result, ms = run_case(c, lambda: FakeTools(), answer_fn=answer, triage_fn=triage)
check(seen["customer"] == "cust_001" and seen["today"] == "2026-11-05", "the case's customer id and date reach billing")
check(isinstance(seen["tools"], FakeTools), "a fresh adapter is made for each case")
check(result["billing"]["ran"] and result["answer"] == "the reply" and isinstance(ms, int), "the reply is the desk's and the latency is measured")
check(result["review"]["queued"] is False, "the stand-in queue is used, nothing real")

print(f"DESK BILLING TESTS: {n} checks passed")
