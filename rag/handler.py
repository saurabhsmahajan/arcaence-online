"""handle_message: one customer message in, one reply out, with the side effects kept out of the desk.

desk_answer() stays a function of the message alone: no database writes, so the evaluation and CI
can run it with a read-only login. This handler is the layer that acts on the handoff flag.

If a message needs a person, it is added to the review queue. If the queue cannot be written, a
reply that says "marking it for review" would be untrue, so the escalate reply is replaced by a
fixed one that promises nothing, and the result says the item was not queued.

Triage runs in SHADOW MODE on messages the classifier called normal or multi. It reads the message,
decides who would own it, and when that is a specialist it adds a routing note to the queue through
enqueue_action. It never changes the reply, and a triage or queue failure never touches the reply.
It lives here, not in desk_answer(), so the evaluation gate keeps scoring the same pipeline.

Billing runs in SHADOW MODE too (BILLING_MODE=shadow), only when triage says refund and the trusted caller
gave a customer id. It runs the billing agent on a rolled-back transaction, records the outcome and a
preview of the words, and changes nothing: not the reply, not the database, not the queue.

The human gate (HUMAN_GATE_QUEUE=on, off by default): when billing's outcome is "queued", the proposal it made is put
into the real review queue through the same writer as routing notes (desk_service, which can add and read items and can
never decide one). That is the only thing this switch changes. The reply is still not changed, nothing is executed, and a
queue failure is recorded by class name and touches nothing else.

Privacy runs in SHADOW MODE the same way (PRIVACY_MODE=shadow), only when triage says privacy and the trusted caller
gave a customer id. It records what it would have opened or cancelled, read from the request tables on a
rolled-back transaction, and a preview of the words. It changes nothing: not the reply, not the database, not the queue.

After the reply is settled, one trace is written for the case (metadata only, see tracing.py). A
tracing failure is swallowed there: it can never change or delay the customer's reply.
"""
import os
import time

import tracing
from billing_logic import CUSTOMER_ID
from billing_reply import billing_reply
from desk_logic import QUEUE_FAILED_REPLY
from privacy_reply import privacy_reply
from triage_logic import SPECIALIST, needs_routing, routing_proposal


def _default_enqueue(result):
    import psycopg
    from review import enqueue_answer

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:  # commits when the block ends
        return enqueue_answer(conn, result)


def _default_triage(question):
    from triage import triage

    return triage(question)


def _default_route(proposal):
    import psycopg
    from review import enqueue_action

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:  # commits when the block ends
        return enqueue_action(conn, **proposal)


def _default_billing():
    from billing_shadow import default_billing_fn

    return default_billing_fn()


def _default_proposal_queue():
    """The writer for billing proposals, or None. Read at each call, not at import: only the exact word "on" turns it on."""
    return _default_route if os.environ.get("HUMAN_GATE_QUEUE") == "on" else None


def _default_privacy():
    from privacy_shadow import default_privacy_fn

    return default_privacy_fn()


def _run_privacy_shadow(result, question, customer_id, privacy_fn):
    """Fills result["privacy"]. Never raises and never touches the reply."""
    p = {"ran": False, "mode": "shadow" if privacy_fn else "off", "skipped": "", "outcome": "", "reason": "", "kind": "",
         "steps": 0, "would_open": False, "would_cancel": False, "preview": "", "error": ""}
    result["privacy"] = p
    tri = result.get("triage", {})
    if privacy_fn is None:
        p["skipped"] = "off"
    elif not tri.get("ran") or tri.get("fallback") or tri.get("intent") != "privacy":
        p["skipped"] = "not_privacy"
    elif not (isinstance(customer_id, str) and CUSTOMER_ID.fullmatch(customer_id)):
        p["skipped"] = "no_customer"    # the id comes from the caller; a message never supplies one
    else:
        try:
            out = privacy_fn(question, result["case_id"], customer_id)
            rec, fx = out["record"], out.get("effects", [])
            p.update(ran=True, outcome=rec.get("outcome") or "", reason=rec.get("reason") or "", kind=rec.get("kind") or "",
                     steps=len(rec.get("steps", [])), would_open=any(e.get("change") == "opened" for e in fx),
                     would_cancel=any(e.get("change") == "cancelled" for e in fx),
                     preview=privacy_reply(rec, queued=True), error=str(rec.get("error") or ""))
        except Exception as exc:  # the class name only
            p["error"] = type(exc).__name__


def _run_billing_shadow(result, question, customer_id, billing_fn, proposal_fn=None):
    """Fills result["billing"]. Never raises and never touches the reply."""
    b = {"ran": False, "mode": "shadow" if billing_fn else "off", "skipped": "", "outcome": "", "reason": "",
         "steps": 0, "would_refund": False, "would_queue": False, "preview": "", "error": "",
         "proposal_queued": False, "proposal_item_id": None, "proposal_error": ""}
    result["billing"] = b
    tri = result.get("triage", {})
    if billing_fn is None:
        b["skipped"] = "off"
    elif not tri.get("ran") or tri.get("fallback") or tri.get("intent") != "refund":
        b["skipped"] = "not_refund"
    elif not (isinstance(customer_id, str) and CUSTOMER_ID.fullmatch(customer_id)):
        b["skipped"] = "no_customer"    # the id comes from the caller; a message never supplies one
    else:
        try:
            out = billing_fn(question, result["case_id"], customer_id)
            rec, refund = out["record"], out.get("refund")
            b.update(ran=True, outcome=rec.get("outcome") or "", reason=rec.get("reason") or "",
                     steps=len(rec.get("steps", [])), would_refund=bool(refund), would_queue=rec.get("outcome") == "queued",
                     preview=billing_reply(rec, refund, queued=True), error=str(rec.get("error") or ""))
            if proposal_fn is not None and b["would_queue"]:
                _queue_proposals(b, out.get("proposals") or [], proposal_fn)
        except Exception as exc:  # the class name only
            b["error"] = type(exc).__name__


def _queue_proposals(b, proposals, proposal_fn):
    """Put each proposal the billing agent made into the review queue. A failure is the class name only and stops here."""
    for proposal in proposals:
        try:
            item = str(proposal_fn(proposal))
        except Exception as exc:  # the class name only: a failure here must never touch the reply
            b["proposal_error"] = type(exc).__name__
            return
        b["proposal_queued"] = True
        b["proposal_item_id"] = b["proposal_item_id"] or item


def _run_triage(result, question, triage_fn, route_fn):
    """Fills result["triage"]. Never raises and never touches the reply."""
    tr = {"ran": False, "intent": "", "specialist": "", "fallback": False, "fallback_reason": "",
          "dropped_facts": [], "routing_queued": False, "item_id": None, "error": ""}
    result["triage"] = tr
    if result.get("label") not in ("normal", "multi"):
        return
    try:
        t = triage_fn(question)
        tr.update(ran=True, intent=t["intent"], specialist=SPECIALIST[t["intent"]],
                  fallback=bool(t["fallback"]), fallback_reason=t["fallback_reason"],
                  dropped_facts=list(t["dropped_facts"]))
        if not t["fallback"] and needs_routing(t):
            try:
                tr["item_id"] = str(route_fn(routing_proposal(result["case_id"], question, t)))
                tr["routing_queued"] = True
            except Exception as exc:  # the class name only
                tr["error"] = type(exc).__name__
    except Exception as exc:
        tr["error"] = type(exc).__name__


def handle_message(question: str, answer_fn=None, enqueue_fn=None, trace_fn=None,
                   triage_fn=None, route_fn=None, customer_id=None, billing_fn=None, privacy_fn=None, proposal_fn=None) -> dict:
    if answer_fn is None:
        from desk import desk_answer as answer_fn
    enqueue_fn = enqueue_fn or _default_enqueue
    trace_fn = trace_fn or tracing.record_case
    triage_fn = triage_fn or _default_triage
    route_fn = route_fn or _default_route
    billing_fn = billing_fn or _default_billing()
    privacy_fn = privacy_fn or _default_privacy()
    proposal_fn = proposal_fn or _default_proposal_queue()
    started = time.perf_counter()

    result = answer_fn(question)
    result["review"] = {"needed": result["handoff"]["needed"], "queued": False, "item_id": None, "error": ""}
    if result["handoff"]["needed"]:
        try:
            result["review"]["item_id"] = str(enqueue_fn(result))
            result["review"]["queued"] = True
        except Exception as exc:  # the class name only: a message could carry connection details
            result["review"]["error"] = type(exc).__name__
            if result["behavior"] == "escalate":
                result["answer"] = QUEUE_FAILED_REPLY

    _run_triage(result, question, triage_fn, route_fn)
    _run_billing_shadow(result, question, customer_id, billing_fn, proposal_fn)
    _run_privacy_shadow(result, question, customer_id, privacy_fn)

    try:
        trace_fn(result, int((time.perf_counter() - started) * 1000))
    except Exception:  # tracing must never touch the reply
        pass
    return result
