"""Triage contract: the intents, the structured handoff, and the checks on it. No model call here.

Triage decides WHO should handle a message, never WHAT to do about it. It has no write tools and
reads no customer data. Its output is a handoff: an intent, the specialist that owns it, and a few
typed facts the message itself states. Everything the model returns is checked here before it is
used, and the queue summary is built by code from fixed words, never from model text.
"""
import re

# intent -> the specialist that owns it ("none" = the existing answer path, no account request)
SPECIALIST = {
    "refund": "billing",
    "subscription": "billing",
    "payment": "billing",
    "privacy": "privacy",
    "account": "account",
    "policy_question": "none",
}
INTENTS = sorted(SPECIALIST)
CURRENCIES = ["EUR", "USD", "INR"]

# Strict ASCII patterns, as in ADR-047: [0-9], never \d. Used with fullmatch, because "$" also accepts a trailing newline.
ORDER_ID = re.compile(r"ord_[0-9]{4}")
AMOUNT = re.compile(r"[0-9]{1,9}(\.[0-9]{1,2})?")

HANDOFF_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "confidence": {"type": "number"},
        "order_id": {"type": ["string", "null"]},
        "amount": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"], "enum": CURRENCIES + [None]},
        "days_since_purchase": {"type": ["integer", "null"]},
    },
    "required": ["intent", "confidence", "order_id", "amount", "currency", "days_since_purchase"],
    "additionalProperties": False,
}

SUMMARY = "Route to the {specialist} agent: the message looks like a {intent} request."


def handoff_problems(h) -> list[str]:
    """Reasons a model handoff cannot be trusted. An empty list means it may be used."""
    if not isinstance(h, dict):
        return ["handoff is not an object"]
    problems = []
    if set(h) != set(HANDOFF_SCHEMA["properties"]):
        problems.append("handoff has missing or unexpected fields")
        return problems
    if h["intent"] not in SPECIALIST:
        problems.append(f"unknown intent {h['intent']!r}")
    c = h["confidence"]
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
        problems.append("confidence is not a number from 0 to 1")
    if h["order_id"] is not None and not (isinstance(h["order_id"], str) and ORDER_ID.fullmatch(h["order_id"])):
        problems.append("order_id does not match ord_ and four digits")
    if h["amount"] is not None and not (isinstance(h["amount"], str) and AMOUNT.fullmatch(h["amount"])):
        problems.append("amount is not plain digits with up to two decimals")
    if h["currency"] is not None and h["currency"] not in CURRENCIES:
        problems.append("currency is not one of the supported ones")
    d = h["days_since_purchase"]
    if d is not None and (isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 3650):
        problems.append("days_since_purchase is not a whole number from 0 to 3650")
    return problems


def needs_routing(h: dict) -> bool:
    """A routing item is queued when the message is an account request for a specialist."""
    return SPECIALIST[h["intent"]] != "none"


def routing_proposal(case_id: str, question: str, h: dict) -> dict:
    """Arguments for review.enqueue_action. It proposes a routing note; it never proposes money."""
    specialist = SPECIALIST[h["intent"]]
    facts = {k: h[k] for k in ("order_id", "amount", "currency", "days_since_purchase") if h[k] is not None}
    return {
        "case_id": case_id,
        "question": question,
        "summary": SUMMARY.format(specialist=specialist, intent=h["intent"]),
        "tool": "route_case",
        "args": {"specialist": specialist, "intent": h["intent"], "facts": facts},
    }
