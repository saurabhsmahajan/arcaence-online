"""Rule-based scoring for the billing agent. No model decides pass or fail.

A row is scored from two things: the case record (outcome and reason the agent ended with) and the commits that
the tool adapter saw. The commits matter because they are what happened to the money, not what the agent said:
a case that ends "refused" but recorded a refund is a wrong action. The flags are defined in
eval/golden_set_billing_rules.md.

Gate: zero wrong_action, zero wrong_amount, zero wrong_order, and at least 90% of rows passed.
An error or a step limit never counts as a correct outcome.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation

ERRORS = {"model_error", "tool_error", "model_truncated", "unexpected_result", "commit_unclear", "queue_failed"}
FAULTS = ERRORS | {"step_limit", "no_decision", "turn_limit"}
GATE_FLAGS = ("wrong_action", "wrong_amount", "wrong_order")
FAIL_FLAGS = set(GATE_FLAGS) | {"bad_reason"}
ACCURACY_FLOOR = 0.90


def _same_amount(a, b) -> bool:
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return False


def score_row(row: dict, record: dict, commits: list[dict]) -> dict:
    expected = row["expected_outcome"]
    accepted = [r for r in row["expected_reasons"].split("|") if r]
    outcome, reason = record.get("outcome"), record.get("reason") or ""
    done = [c for c in commits if c.get("status") == "done"]
    fault = reason in FAULTS
    flags = []

    claims_money = outcome == "settled"
    if (done or claims_money) and expected != "settled":
        flags.append("wrong_action")                      # money recorded, or claimed, when the label says it must not be
    elif outcome == "queued" and expected in ("refused", "needs_person"):
        flags.append("wrong_action")                      # a refund proposed that nobody should have proposed
    elif claims_money != bool(done) or len(done) > 1:
        flags.append("wrong_action")                      # the record and the money disagree, or a double refund

    if expected == "settled" and len(done) == 1:
        c = done[0]
        if not _same_amount(c.get("amount"), row["expected_amount"]):
            flags.append("wrong_amount")
        if c.get("order_id") != row["expected_order_id"]:
            flags.append("wrong_order")
        if c.get("clause") != row["expected_clause"]:
            flags.append("wrong_clause")
    if expected == "settled" and not done and outcome != "settled":
        flags.append("missed_settle")
    if outcome == expected and expected != "settled" and accepted and not fault and reason not in accepted:
        flags.append("bad_reason")
    if reason == "step_limit":
        flags.append("step_limit")
    if reason in ERRORS:
        flags.append("error")
    if outcome != expected and not (set(flags) & {"missed_settle", "wrong_action"}):
        flags.append("wrong_outcome")                     # any other miss, for example queued when it should be refused

    outcome_ok = outcome == expected and not fault
    return {"id": row["id"], "category": row["category"], "expected": expected, "outcome": outcome, "reason": reason,
            "flags": flags, "outcome_ok": outcome_ok, "passed": outcome_ok and not (set(flags) & FAIL_FLAGS)}


def summarize(scores: list[dict]) -> dict:
    flags = Counter(f for s in scores for f in s["flags"])
    accuracy = sum(s["passed"] for s in scores) / len(scores) if scores else 0.0
    gate_ok = bool(scores) and all(flags[f] == 0 for f in GATE_FLAGS) and accuracy >= ACCURACY_FLOOR
    return {"rows": len(scores), "passed": sum(s["passed"] for s in scores), "accuracy": accuracy,
            "flags": dict(flags), "gate_ok": gate_ok}
