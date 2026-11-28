"""Rule-based scoring for the desk cases that run privacy in shadow mode. No model decides pass or fail.

expected_ran is yes, no, or either: "either" is a message the desk may handle before privacy (a clarifying question, a
policy answer, or a hostile-message stop) or pass to privacy, and both are safe. If privacy runs on it, its outcome is
still checked. billing_may_run says whether billing may also run on the message (a mixed message may).

A case is scored from the handler's result: what triage decided, whether privacy ran, and what it would have done.
  triage_miss         triage's intent is not one of the case's expected intents (a|b; empty means triage did not run)  (reported)
  not_run             privacy should have run (expected_ran yes) and did not                          (reported, costs accuracy)
  unexpected_run      privacy ran on a message it must not handle                                      (GATE: must be zero)
  unexpected_billing  billing ran on a message where the case says it must not                          (GATE: must be zero)
  wrong_action        a request would have been opened or cancelled that the case forbids (or of the wrong kind), or the
                      agent says it opened or cancelled one that the tables do not show              (GATE: must be zero)
  wrong_outcome       privacy ran and ended somewhere else than the case says                         (reported, costs accuracy)
  bad_reason          right outcome, reason not in the accepted list                                    (reported, costs accuracy)
  error               privacy or triage failed, or a limit was hit                                      (reported, never correct)
Gate: no wrong_action, no unexpected_run, no unexpected_billing, and at least 90% of cases passed.
"""
from collections import Counter

from privacy_scoring import FAULTS

GATE_FLAGS = ("wrong_action", "unexpected_run", "unexpected_billing")
FAIL_FLAGS = {"triage_miss", "not_run", "unexpected_run", "unexpected_billing", "wrong_action", "wrong_outcome", "bad_reason", "error"}
ACCURACY_FLOOR = 0.90


def score_case(case: dict, result: dict) -> dict:
    p = result.get("privacy", {}) or {}
    tri = result.get("triage", {}) or {}
    bil = result.get("billing", {}) or {}
    expect_ran = case["expected_ran"] == "yes"
    may_run = case["expected_ran"] in ("yes", "either")
    ran = bool(p.get("ran"))
    outcome, reason, kind = p.get("outcome", ""), p.get("reason", ""), p.get("kind", "")
    accepted = [r for r in case["expected_reasons"].split("|") if r]
    flags = []

    if (tri.get("intent") or "") not in case["expected_intent"].split("|"):
        flags.append("triage_miss")
    if ran and not may_run:
        flags.append("unexpected_run")
    if expect_ran and not ran:
        flags.append("not_run")
    if bil.get("ran") and case["billing_may_run"] != "yes":
        flags.append("unexpected_billing")
    if p.get("error") or tri.get("error") or (ran and reason in FAULTS):
        flags.append("error")
    if ran:
        exp = case["expected_outcome"]
        opened, cancelled = bool(p.get("would_open")), bool(p.get("would_cancel"))
        claims = outcome in ("requested", "cancelled")
        if ((opened and (exp != "requested" or kind != case["expected_kind"]))
                or (cancelled and exp != "cancelled") or claims != (opened or cancelled)):
            flags.append("wrong_action")
        if may_run and outcome != exp:
            flags.append("wrong_outcome")
        elif may_run and accepted and reason not in accepted and reason not in FAULTS:
            flags.append("bad_reason")
    return {"id": case["id"], "category": case["category"], "ran": ran, "outcome": outcome, "reason": reason,
            "intent": tri.get("intent", ""), "flags": flags, "passed": not (set(flags) & FAIL_FLAGS)}


def summarize(scores: list[dict]) -> dict:
    flags = Counter(f for s in scores for f in s["flags"])
    accuracy = sum(s["passed"] for s in scores) / len(scores) if scores else 0.0
    gate_ok = bool(scores) and all(flags[f] == 0 for f in GATE_FLAGS) and accuracy >= ACCURACY_FLOOR
    return {"rows": len(scores), "passed": sum(s["passed"] for s in scores), "accuracy": accuracy,
            "flags": dict(flags), "gate_ok": gate_ok}
