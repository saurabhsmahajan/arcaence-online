"""Rule-based scoring for triage. No model decides pass or fail.

Per row (expected = a golden set row, got = a triage() result):
  false route     expected no specialist, got one                  (a question became an account action)
  missed route    expected a specialist, got none
  wrong owner     both routed, different specialist
  invented fact   a typed fact in the result that is not in the expected facts, or has another value
  missing fact    an expected fact that the result left out
A row passes when the intent matches, no fact is invented or missing, and the fallback did not run.
A fallback never counts as a correct intent, even when its safe default equals the expected one.

Gate on single-request rows (category multi is reported apart):
  no false route, no invented fact, and at least 90% intent accuracy.
"""
import json
from collections import Counter

from triage_logic import SPECIALIST

FACT_KEYS = ("order_id", "amount", "currency", "days_since_purchase")
ACCURACY_FLOOR = 0.90


def got_facts(got: dict) -> dict:
    return {k: got[k] for k in FACT_KEYS if got.get(k) is not None}


def score_row(row: dict, got: dict) -> dict:
    expected = json.loads(row["expected_facts"] or "{}")
    facts = got_facts(got)
    invented = sorted(k for k, v in facts.items() if expected.get(k) != v)
    missing = sorted(k for k in expected if k not in facts)
    exp_owner = row["expected_specialist"]
    got_owner = SPECIALIST[got["intent"]]
    flags = []
    if exp_owner == "none" and got_owner != "none":
        flags.append("false_route")
    elif exp_owner != "none" and got_owner == "none":
        flags.append("missed_route")
    elif exp_owner != got_owner:
        flags.append("wrong_owner")
    if invented:
        flags.append("invented_fact")
    if missing:
        flags.append("missing_fact")
    if got.get("fallback"):
        flags.append("fallback")
    intent_ok = got["intent"] == row["expected_intent"] and not got.get("fallback")  # a fallback right by luck is not right
    return {"id": row["id"], "category": row["category"], "intent_ok": intent_ok,
            "flags": flags, "invented": invented, "missing": missing,
            "passed": intent_ok and not (set(flags) & {"invented_fact", "missing_fact", "fallback"})}


def summarize(scores: list[dict]) -> dict:
    single = [s for s in scores if s["category"] != "multi"]
    multi = [s for s in scores if s["category"] == "multi"]
    flags = Counter(f for s in single for f in s["flags"])
    accuracy = sum(s["intent_ok"] for s in single) / len(single) if single else 0.0
    gate_ok = bool(single) and flags["false_route"] == 0 and flags["invented_fact"] == 0 and accuracy >= ACCURACY_FLOOR
    return {"rows": len(single), "passed": sum(s["passed"] for s in single), "intent_accuracy": accuracy,
            "flags": dict(flags), "multi_rows": len(multi), "multi_passed": sum(s["passed"] for s in multi),
            "gate_ok": gate_ok}
