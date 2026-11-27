"""The words a customer gets after the billing agent has finished. Fixed text, written here, never by a model.

The model never writes to the customer (ADR-051). Each reply says only what code knows to be true:
  settled      a refund was recorded: the server said "done". The amount, currency and order come from that
               result and are checked against a strict pattern before they go into the words.
  queued       a person will decide: said only when the queue returned an id (ADR-058).
  refused      one wording for every refusal, so a reply cannot tell a customer that someone else's order
               exists or why it was refused beyond "the conditions are not met".
  needs_person "passed to our team" is said only when the case really was queued; otherwise the reply
               promises nothing and points to the Help Centre.
Nothing from the customer's message, the order record or the model's output is ever copied into a reply.
"""
import re

from billing_logic import AMOUNT, ORDER_ID

CURRENCIES = {"EUR", "USD", "INR"}
_AMOUNT = re.compile(AMOUNT) if isinstance(AMOUNT, str) else AMOUNT
_ORDER = re.compile(ORDER_ID) if isinstance(ORDER_ID, str) else ORDER_ID

SETTLED = "Your refund of {amount} {currency} for order {order_id} has been recorded."
SETTLED_PLAIN = "Your refund has been recorded."
QUEUED = ("This refund is above the amount I can approve myself, so I have passed it to our team to decide. "
          "I can't say yet whether it will be approved.")
REFUSED = ("I'm sorry, I can't refund this: it does not meet the refund conditions in our terms. "
           "If you think that is wrong, the Help Centre can look at it.")
ASK_DETAILS = "Could you tell me which order you mean and how much you would like refunded?"
NOT_SUPPORTED = "I can only help with refund requests here. The Help Centre can help with this."
PERSON_QUEUED = "I can't decide this myself, so I have passed it to our team to look at."
PERSON_NOT_QUEUED = ("I'm sorry, I could not pass your message to our team just now. "
                     "Please contact the Help Centre so a person can look at it.")
UNCLEAR_COMMIT = ("I'm sorry, I can't tell whether your refund went through, so I am not going to say it did. "
                  "Please contact the Help Centre so a person can check.")

ALL_REPLIES = (SETTLED, SETTLED_PLAIN, QUEUED, REFUSED, ASK_DETAILS, NOT_SUPPORTED, PERSON_QUEUED, PERSON_NOT_QUEUED, UNCLEAR_COMMIT)


def _refund_words(refund):
    """The settled sentence, with the figures only if all three are exactly what a server result looks like."""
    if isinstance(refund, dict):
        amount, currency, order_id = refund.get("amount"), refund.get("currency"), refund.get("order_id")
        if (isinstance(amount, str) and _AMOUNT.fullmatch(amount) and currency in CURRENCIES
                and isinstance(order_id, str) and _ORDER.fullmatch(order_id)):
            return SETTLED.format(amount=amount, currency=currency, order_id=order_id)
    return SETTLED_PLAIN


def billing_reply(record: dict, refund: dict | None = None, queued: bool = False) -> str:
    """The reply for a finished case. `record` is CaseRecord.to_dict(); `refund` the server's commit result;
    `queued` says whether the case really reached the review queue (only the handler knows)."""
    outcome, reason = record.get("outcome"), record.get("reason") or ""
    if outcome == "settled":
        return _refund_words(refund)
    if outcome == "queued" and record.get("item_id"):
        return QUEUED
    if outcome == "refused":
        return REFUSED
    if outcome == "needs_person":
        if reason == "missing_details":
            return ASK_DETAILS
        if reason == "not_supported":
            return NOT_SUPPORTED
        if reason == "commit_unclear":
            return UNCLEAR_COMMIT
        return PERSON_QUEUED if queued else PERSON_NOT_QUEUED
    return PERSON_QUEUED if queued else PERSON_NOT_QUEUED   # anything unexpected promises nothing it cannot keep
