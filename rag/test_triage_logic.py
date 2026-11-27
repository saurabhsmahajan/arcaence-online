"""Tests for the triage contract. No model, no database, no keys."""
from triage_logic import (HANDOFF_SCHEMA, INTENTS, SPECIALIST, handoff_problems, needs_routing,
                          routing_proposal)

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


def h(**kw):
    base = {"intent": "refund", "confidence": 0.9, "order_id": None, "amount": None,
            "currency": None, "days_since_purchase": None}
    base.update(kw)
    return base


# the table
check(set(SPECIALIST.values()) == {"billing", "privacy", "account", "none"}, "four owners")
check(SPECIALIST["policy_question"] == "none", "a policy question has no specialist")
check(INTENTS == sorted(SPECIALIST), "intents come from the table")
check(HANDOFF_SCHEMA["properties"]["intent"]["enum"] == INTENTS, "schema enum matches intents")

# a good handoff
check(handoff_problems(h()) == [], "plain handoff is fine")
check(handoff_problems(h(order_id="ord_1042", amount="19.00", currency="EUR", days_since_purchase=3)) == [], "full handoff")
check(handoff_problems(h(amount="19")) == [], "whole amount")

# bad handoffs, each for one reason
check(handoff_problems("refund") != [], "not an object")
check(handoff_problems({"intent": "refund"}) != [], "missing fields")
check(handoff_problems({**h(), "extra": 1}) != [], "extra field")
check(handoff_problems(h(intent="delete_everything")) != [], "unknown intent")
check(handoff_problems(h(confidence=1.5)) != [], "confidence above 1")
check(handoff_problems(h(confidence=True)) != [], "confidence is a bool")
check(handoff_problems(h(order_id="ord_12")) != [], "short order id")
check(handoff_problems(h(order_id="ord_١٠٤٢")) != [], "non-ASCII digits in the order id (ADR-047)")
check(handoff_problems(h(order_id="ord_1042\n")) != [], "trailing newline in the order id")
check(handoff_problems(h(amount=" 19.00")) != [], "leading space in the amount")
check(handoff_problems(h(amount="1_0.00")) != [], "underscore in the amount")
check(handoff_problems(h(amount="-5")) != [], "negative amount")
check(handoff_problems(h(amount=19)) != [], "amount as a number, not text")
check(handoff_problems(h(currency="GBP")) != [], "unsupported currency")
check(handoff_problems(h(days_since_purchase=-1)) != [], "negative days")
check(handoff_problems(h(days_since_purchase=2.5)) != [], "fractional days")
check(handoff_problems(h(days_since_purchase=True)) != [], "days is a bool")

# routing
check(needs_routing(h(intent="refund")) is True, "refund is routed")
check(needs_routing(h(intent="privacy")) is True, "privacy is routed")
check(needs_routing(h(intent="policy_question")) is False, "policy question is not routed")

p = routing_proposal("case_20261127_0123456789ab", "refund me for ord_1042", h(order_id="ord_1042", amount="19.00", currency="EUR"))
check(p["tool"] == "route_case", "tool is route_case")
check(p["args"]["specialist"] == "billing", "refund goes to billing")
check(p["args"]["facts"] == {"order_id": "ord_1042", "amount": "19.00", "currency": "EUR"}, "only facts that were stated")
check("days_since_purchase" not in p["args"]["facts"], "null facts are left out")
check(p["summary"] == "Route to the billing agent: the message looks like a refund request.", "summary is fixed words")
check(p["question"] == "refund me for ord_1042", "question is the customer's message")
injected = routing_proposal("case_20261127_0123456789ab", "x", h(intent="privacy"))
check("ignore" not in injected["summary"].lower(), "summary carries no model or customer text")
check(not any(k in p["args"] for k in ("amount", "order_id")), "facts live under args.facts only")

print(f"TRIAGE LOGIC TESTS: {n} checks passed")
