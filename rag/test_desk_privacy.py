"""Checks the privacy desk cases against the world they describe, tests the scorer and the runner's wiring. No model, database or keys."""
import csv

import tracing
tracing.use_client(None)
from billing_logic import CUSTOMER_ID
from desk_privacy_scoring import ACCURACY_FLOOR, GATE_FLAGS, score_case, summarize
from privacy_fakes import make
from privacy_logic import ALLOWED_REASONS, OUTCOMES
from privacy_tools import SETUPS
from run_desk_privacy_cases import CASES, run_case
from triage_logic import INTENTS

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


COLUMNS = ["id", "message", "customer_id", "setup", "expected_intent", "expected_ran", "expected_outcome", "expected_kind",
           "expected_reasons", "billing_may_run", "category", "notes"]

# --- the case file -------------------------------------------------------------------------------------------------
with CASES.open(encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    check(reader.fieldnames == COLUMNS, "the columns are as documented")
    cases = list(reader)
check(len(cases) == 17, "there are seventeen privacy desk cases")
check([c["id"] for c in cases] == [f"DP{i:02d}" for i in range(1, 18)], "ids DP01 to DP17, once each")
for c in cases:
    i = c["id"]
    check(CUSTOMER_ID.fullmatch(c["customer_id"]) is not None, f"{i}: the customer id has the right shape")
    check(c["setup"] in SETUPS, f"{i}: the setup is known")
    check(all(p in INTENTS or p == "" for p in c["expected_intent"].split("|")), f"{i}: each expected intent is real, or empty for a message the desk stops before triage")
    check(c["expected_ran"] in ("yes", "no", "either") and c["billing_may_run"] in ("yes", "no"), f"{i}: expected_ran and billing_may_run are closed words")
    check(c["expected_kind"] in ("", "deletion", "export"), f"{i}: the kind is known")
    check(c["message"].strip() != "" and c["category"] != "" and c["notes"] != "", f"{i}: has a message, a category and a note")
    if c["expected_ran"] == "no":
        check(c["expected_outcome"] == "" and c["expected_reasons"] == "" and c["expected_kind"] == "", f"{i}: a case where privacy must not run has no outcome")
        check("privacy" not in c["expected_intent"].split("|"), f"{i}: and is not a privacy message")
    else:
        check(c["expected_outcome"] in OUTCOMES, f"{i}: a privacy case has a real outcome")
        if c["expected_outcome"] in ("requested", "cancelled"):
            check(c["expected_reasons"] == "" and c["expected_kind"] != "", f"{i}: an acted case has a kind and no reason")
        else:
            allowed = ALLOWED_REASONS[c["expected_outcome"]]
            check(c["expected_reasons"] != "" and set(c["expected_reasons"].split("|")) <= set(allowed), f"{i}: reasons come from the contract's list")
        check((c["expected_ran"] == "either") == ("|" in c["expected_intent"]), f"{i}: only an either case accepts more than one path")
by = {c["id"]: c for c in cases}
check(by["DP04"]["setup"] == "open_deletion" and by["DP04"]["expected_outcome"] == "cancelled", "DP04: a cancel starts with an open deletion request")
check(by["DP05"]["setup"] == "none" and by["DP05"]["expected_reasons"] == "no_open_request", "DP05: a cancel with nothing open is refused by the tool")
check(by["DP06"]["setup"] == "open_export" and by["DP06"]["expected_kind"] == "export" and by["DP06"]["expected_reasons"] == "request_already_open", "DP06: a duplicate meets an open export request")
check(by["DP08"]["customer_id"] == "cust_001" and "cust_002" in by["DP08"]["message"] and by["DP08"]["expected_reasons"] == "not_eligible", "DP08: asks about another account and is refused as not eligible")
check(by["DP11"]["billing_may_run"] == "yes" and by["DP11"]["expected_kind"] == "deletion", "DP11: a mixed message may reach billing and privacy opens only a deletion request")
check(by["DP03"]["expected_ran"] == "either" and by["DP03"]["expected_intent"] == "|privacy" and "Corrected after run 1" in by["DP03"]["notes"],
      "DP03: a threat may be stopped as hostile before triage, and the correction is recorded in the note")
check(by["DP17"]["expected_ran"] == "yes" and by["DP17"]["expected_outcome"] == "requested" and not any(w in by["DP17"]["message"].lower() for w in ("press", "lawyer", "court", "regulator")),
      "DP17: urgency with no threat must reach privacy and open the request")
check({c["customer_id"] for c in cases} == {"cust_001", "cust_002"}, "both customers are used")
check(sum(c["expected_ran"] == "no" for c in cases) == 3 and sum(c["expected_ran"] == "yes" for c in cases) >= 8, "there are non-privacy cases and plenty of privacy cases")

# --- the scorer ----------------------------------------------------------------------------------------------------


def res(intent="privacy", ran=True, outcome="requested", reason="", kind="deletion", opened=True, cancelled=False, error="", tri_error="",
        billing=False, skipped=""):
    return {"triage": {"intent": intent, "error": tri_error},
            "privacy": {"ran": ran, "outcome": outcome if ran else "", "reason": reason if ran else "", "kind": kind if ran else "",
                        "would_open": opened, "would_cancel": cancelled, "error": error, "skipped": skipped},
            "billing": {"ran": billing}}


def case(**kw):
    base = dict(by["DP01"])
    base.update(kw)
    return base


s = score_case(case(), res())
check(s["passed"] and s["flags"] == [], "a correct request passes")
s = score_case(case(), res(kind="export"))
check("wrong_action" in s["flags"] and not s["passed"], "the wrong kind of request opened is a wrong action")
s = score_case(case(), res(opened=False))
check("wrong_action" in s["flags"], "saying a request was opened when the tables do not show it is a wrong action")
s = score_case(by["DP05"], res(outcome="refused", reason="no_open_request", kind="deletion", opened=False))
check(s["passed"], "a tool refusal with no change passes")
s = score_case(by["DP05"], res(outcome="requested", opened=True))
check("wrong_action" in s["flags"] and "wrong_outcome" in s["flags"], "opening a request when none was wanted is wrong")
s = score_case(by["DP04"], res(outcome="cancelled", opened=False, cancelled=True))
check(s["passed"], "a correct cancel passes")
s = score_case(by["DP04"], res(outcome="cancelled", opened=False, cancelled=False))
check("wrong_action" in s["flags"], "a claimed cancel that did not happen is a wrong action")
s = score_case(by["DP01"], res(outcome="refused", reason="not_eligible", opened=False))
check("wrong_outcome" in s["flags"] and "wrong_action" not in s["flags"] and not s["passed"], "refusing a plain request is a wrong outcome, not a wrong action")
s = score_case(by["DP12"], res(outcome="needs_person", reason="not_supported", opened=False))
check("bad_reason" in s["flags"] and not s["passed"], "the right outcome with the wrong reason fails")
s = score_case(by["DP12"], res(outcome="needs_person", reason="tool_error", opened=False))
check("error" in s["flags"] and not s["passed"], "a fault never counts as correct")
s = score_case(by["DP12"], res(outcome="needs_person", reason="unclear_request", opened=False))
check(s["passed"], "a correct hand-off passes")
s = score_case(by["DP14"], res(intent="account", ran=False, outcome="", opened=False, skipped="not_privacy"))
check(s["passed"], "a non-privacy message that did not reach privacy passes")
s = score_case(by["DP14"], res(intent="privacy", outcome="needs_person", reason="not_supported", opened=False))
check("unexpected_run" in s["flags"] and "triage_miss" in s["flags"], "privacy running on a non-privacy message is unexpected_run")
s = score_case(by["DP01"], res(ran=False, opened=False))
check("not_run" in s["flags"] and not s["passed"], "privacy not running on a plain request is not_run")
s = score_case(by["DP07"], res(intent="policy_question", ran=False, opened=False))
check(s["passed"], "an either case may stop before privacy")
s = score_case(by["DP07"], res(intent="privacy", outcome="needs_person", reason="unclear_request", opened=False))
check(s["passed"], "and may reach it")
s = score_case(by["DP10"], res(intent="", ran=False, opened=False))
check(s["passed"], "a hostile message stopped before triage passes")
s = score_case(by["DP01"], res(billing=True))
check("unexpected_billing" in s["flags"] and not s["passed"], "billing running on a privacy message is flagged")
s = score_case(by["DP11"], res(billing=True))
check("unexpected_billing" not in s["flags"], "but a mixed message may reach billing")
s = score_case(by["DP01"], res(tri_error="RuntimeError"))
check("error" in s["flags"] and not s["passed"], "a triage error is an error")

# --- the summary ---------------------------------------------------------------------------------------------------
ok = {"flags": [], "passed": True}
sm = summarize([ok] * 9 + [{"flags": ["wrong_outcome"], "passed": False}])
check(sm["gate_ok"] and abs(sm["accuracy"] - ACCURACY_FLOOR) < 1e-9, "90% with no gate flags passes")
check(not summarize([ok] * 8 + [{"flags": ["wrong_outcome"], "passed": False}] * 2)["gate_ok"], "below 90% fails")
for g in GATE_FLAGS:
    check(not summarize([ok] * 99 + [{"flags": [g], "passed": False}])["gate_ok"], f"one {g} fails the gate at 99%")
check(not summarize([])["gate_ok"], "no rows is not a pass")

# --- the runner ----------------------------------------------------------------------------------------------------


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class Reply:
    def __init__(self, *blocks, stop="tool_use"):
        self.content, self.stop_reason = list(blocks), stop


def scripted(name, **inp):
    sent = []

    def create(**kw):
        sent.append(kw)
        return Reply(Block(type="tool_use", id="tu", name=name, input=inp)) if len(sent) == 1 else Reply(stop="end_turn")
    return create


def answer(q):
    return {"question": q, "case_id": "case_20261128_aaaaaaaaaaaa", "label": "normal", "behavior": "answer", "answer": "the reply",
            "handoff": {"needed": False, "reason": ""}}


def triage(intent):
    base = {"intent": intent, "confidence": 0.9, "order_id": None, "amount": None, "currency": None, "days_since_purchase": None,
            "dropped_facts": [], "fallback": False, "fallback_reason": ""}
    return lambda q: base


tools, db, conns = make()
r, ms = run_case(by["DP01"], lambda: tools, privacy_create_fn=scripted("request_account_deletion"), answer_fn=answer, triage_fn=triage("privacy"))
check(r["privacy"]["ran"] and r["privacy"]["outcome"] == "requested" and r["privacy"]["would_open"], "a case runs through the handler end to end")
check(score_case(by["DP01"], r)["passed"] and r["answer"] == "the reply", "and scores as passed with the reply unchanged")
check(db == [] and conns[-1].rolled, "and nothing is kept")
check(r["billing"]["ran"] is False, "billing did not run on a privacy message")

r, _ = run_case(by["DP04"], lambda: tools, privacy_create_fn=scripted("cancel_deletion_request"), answer_fn=answer, triage_fn=triage("privacy"))
check(r["privacy"]["outcome"] == "cancelled" and r["privacy"]["would_cancel"] and score_case(by["DP04"], r)["passed"], "a case with a setup meets the open request and cancels it")
check(db == [], "and the setup is rolled back too")

r, _ = run_case(by["DP06"], lambda: tools, privacy_create_fn=scripted("request_data_export"), answer_fn=answer, triage_fn=triage("privacy"))
check(r["privacy"]["outcome"] == "refused" and r["privacy"]["reason"] == "request_already_open" and score_case(by["DP06"], r)["passed"], "a duplicate meets its open export request and is refused")

r, _ = run_case(by["DP16"], lambda: tools, privacy_create_fn=scripted("request_account_deletion"), answer_fn=answer, triage_fn=triage("refund"))
check(r["privacy"]["ran"] is False and r["billing"]["ran"] is True and score_case(by["DP16"], r)["passed"], "a refund message does not reach privacy, and the billing spy ran harmlessly")

print(f"DESK PRIVACY TESTS: {n} checks passed")
