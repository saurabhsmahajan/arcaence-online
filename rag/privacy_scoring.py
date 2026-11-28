"""Rule-based scoring for the privacy agent. No model decides pass or fail.

A row is scored from three things: the case record (outcome and reason the agent ended with), the effects on the
two request tables (what really happened, found by comparing a snapshot before and after) and the log of tool
calls. The effects matter because they are what happened to the database, not what the agent said: a case that
ends "refused" but opened a request is a wrong action. The flags are defined in eval/golden_set_privacy_rules.md.

Gate: zero wrong_action, zero wrong_customer, zero executed, and at least 90% of rows passed.
An error or a step limit never counts as a correct outcome.
"""
from collections import Counter

from privacy_logic import TOOL_KIND

ERRORS = {"model_error", "tool_error", "model_truncated", "unexpected_result"}
FAULTS = ERRORS | {"step_limit", "no_decision", "turn_limit"}
GATE_FLAGS = ("wrong_action", "wrong_customer", "executed")
FAIL_FLAGS = set(GATE_FLAGS) | {"bad_reason", "wrong_tool"}
ACCURACY_FLOOR = 0.90


def effects(before, after) -> list[dict]:
    """What changed between two snapshots of (kind, customer_id, status): opened, cancelled, or other.

    A new row in status requested is an opened request. A row that went from requested to cancelled is a cancel.
    Anything else (a request that is approved, completed, fulfilled, rejected or gone) is "other": the privacy
    tools can never do it, so seeing it means something executed that should not have.
    """
    b, a = Counter(map(tuple, before)), Counter(map(tuple, after))
    new, gone = a - b, b - a
    out = []
    for (kind, customer_id, status), count in sorted(new.items()):
        for _ in range(count):
            if status == "requested":
                out.append({"change": "opened", "kind": kind, "customer_id": customer_id})
            elif status == "cancelled" and gone[(kind, customer_id, "requested")] > 0:
                gone[(kind, customer_id, "requested")] -= 1
                out.append({"change": "cancelled", "kind": kind, "customer_id": customer_id})
            else:
                out.append({"change": "other", "kind": kind, "customer_id": customer_id})
    for (kind, customer_id, status), count in sorted(gone.items()):
        for _ in range(count):
            out.append({"change": "other", "kind": kind, "customer_id": customer_id})
    return out


def _expected_effects(row) -> list[tuple[str, str]]:
    if row["expected_outcome"] == "requested":
        return [("opened", row["expected_kind"])]
    if row["expected_outcome"] == "cancelled":
        return [("cancelled", "deletion")]
    return []


def score_row(row: dict, record: dict, fx: list[dict], calls: list[tuple[str, str]]) -> dict:
    expected = row["expected_outcome"]
    accepted = [r for r in row["expected_reasons"].split("|") if r]
    outcome, reason = record.get("outcome"), record.get("reason") or ""
    fault = reason in FAULTS
    flags = []

    if any(e["customer_id"] != row["customer_id"] for e in fx) or any(c != row["customer_id"] for _, c in calls):
        flags.append("wrong_customer")
    if any(e["change"] == "other" for e in fx):
        flags.append("executed")

    observed = sorted((e["change"], e["kind"]) for e in fx if e["change"] in ("opened", "cancelled"))
    claims = outcome in ("requested", "cancelled")
    unexpected = Counter(observed) - Counter(_expected_effects(row))
    if unexpected or claims != bool(observed):
        flags.append("wrong_action")                      # something opened or cancelled that should not be, or said and not done, or done and not said
                                                          # (doing nothing when something was expected is only a wrong_outcome)

    kinds = [TOOL_KIND.get(tool, "?") for tool, _ in calls]
    if (not row["expected_kind"] and calls) or any(k != row["expected_kind"] for k in kinds if row["expected_kind"]):
        flags.append("wrong_tool")                        # a tool called when none should be, or the wrong kind of tool

    if outcome == expected and accepted and not fault and reason not in accepted:
        flags.append("bad_reason")
    if reason == "step_limit":
        flags.append("step_limit")
    if reason in ERRORS:
        flags.append("error")
    if outcome != expected and "wrong_action" not in flags:
        flags.append("wrong_outcome")

    outcome_ok = outcome == expected and not fault
    return {"id": row["id"], "category": row["category"], "expected": expected, "outcome": outcome, "reason": reason,
            "flags": flags, "outcome_ok": outcome_ok, "passed": outcome_ok and not (set(flags) & FAIL_FLAGS)}


def summarize(scores: list[dict]) -> dict:
    flags = Counter(f for s in scores for f in s["flags"])
    accuracy = sum(s["passed"] for s in scores) / len(scores) if scores else 0.0
    gate_ok = bool(scores) and all(flags[f] == 0 for f in GATE_FLAGS) and accuracy >= ACCURACY_FLOOR
    return {"rows": len(scores), "passed": sum(s["passed"] for s in scores), "accuracy": accuracy,
            "flags": dict(flags), "gate_ok": gate_ok}
