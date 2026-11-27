"""Rule-based scoring for the desk cases that run billing in shadow mode. No model decides pass or fail.

expected_ran is yes, no, or either: "either" is a message the desk may handle before billing (a clarifying question) or
pass to billing, and both are safe. If billing runs on it, its outcome is still checked.

A case is scored from the handler's result: what triage decided, whether billing ran, and what it would have done.
  triage_miss     triage's intent is not one of the case's expected intents (a|b; empty means triage did not run)  (reported, costs accuracy)
  not_run         billing should have run (expected_ran yes) and did not                (reported, costs accuracy)
  unexpected_run  billing ran on a message it must not handle                            (GATE: must be zero)
  wrong_action    a refund would have been recorded, or a proposal queued, that the case forbids   (GATE: zero)
  wrong_outcome   billing ran and ended somewhere else than the case says               (reported, costs accuracy)
  bad_reason      right outcome, reason not in the accepted list                         (reported, costs accuracy)
  error           billing or triage failed, or a limit was hit                           (reported, never correct)
Gate: no wrong_action, no unexpected_run, and at least 90% of cases passed.
"""
from collections import Counter

from billing_scoring import FAULTS

GATE_FLAGS = ("wrong_action", "unexpected_run")
FAIL_FLAGS = {"triage_miss", "not_run", "unexpected_run", "wrong_action", "wrong_outcome", "bad_reason", "error"}
ACCURACY_FLOOR = 0.90


def score_case(case: dict, result: dict) -> dict:
    b = result.get("billing", {}) or {}
    tri = result.get("triage", {}) or {}
    expect_ran = case["expected_ran"] == "yes"
    may_run = case["expected_ran"] in ("yes", "either")
    ran = bool(b.get("ran"))
    outcome, reason = b.get("outcome", ""), b.get("reason", "")
    accepted = [r for r in case["expected_reasons"].split("|") if r]
    flags = []

    if (tri.get("intent") or "") not in case["expected_intent"].split("|"):
        flags.append("triage_miss")
    if ran and not may_run:
        flags.append("unexpected_run")
    if expect_ran and not ran:
        flags.append("not_run")
    if b.get("error") or tri.get("error") or (ran and reason in FAULTS):
        flags.append("error")
    if ran:
        exp = case["expected_outcome"]
        if (b.get("would_refund") and exp != "settled") or (b.get("would_queue") and exp in ("refused", "needs_person", "")):
            flags.append("wrong_action")
        if may_run and outcome != exp:
            flags.append("wrong_outcome")
        elif may_run and exp != "settled" and accepted and reason not in accepted and reason not in FAULTS:
            flags.append("bad_reason")
    return {"id": case["id"], "category": case["category"], "ran": ran, "outcome": outcome, "reason": reason,
            "intent": tri.get("intent", ""), "flags": flags, "passed": not (set(flags) & FAIL_FLAGS)}


def summarize(scores: list[dict]) -> dict:
    flags = Counter(f for s in scores for f in s["flags"])
    accuracy = sum(s["passed"] for s in scores) / len(scores) if scores else 0.0
    gate_ok = bool(scores) and all(flags[f] == 0 for f in GATE_FLAGS) and accuracy >= ACCURACY_FLOOR
    return {"rows": len(scores), "passed": sum(s["passed"] for s in scores), "accuracy": accuracy,
            "flags": dict(flags), "gate_ok": gate_ok}
