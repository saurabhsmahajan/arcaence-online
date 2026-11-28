"""Offline tests for the human gate in the handler: a billing proposal goes to the queue only when the switch is on. No model, no database."""
import json
import os

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import tracing
tracing.use_client(None)
from handler import _default_proposal_queue, _default_route, handle_message

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


CASE = "case_20261128_bbbbbbbbbbbb"
MSG = "Can I have the 540.00 USD back for my annual Team plan ord_2001? I renewed it by mistake."
PROPOSAL = {"case_id": CASE, "question": MSG, "summary": "Refund 540.00 USD on ord_2001 (over the cap)", "tool": "issue_refund",
            "args": {"customer_id": "cust_002", "order_id": "ord_2001", "amount": "540.00", "clause_doc": "tos_v3", "clause_id": "3.3"}}


def answer(q):
    return {"question": q, "case_id": CASE, "label": "normal", "behavior": "answer", "answer": "the reply", "handoff": {"needed": False, "reason": ""}}


def triage(q):
    return {"intent": "refund", "confidence": 0.9, "order_id": None, "amount": None, "currency": None, "days_since_purchase": None,
            "dropped_facts": [], "fallback": False, "fallback_reason": ""}


def billing(outcome="queued", reason="over_cap", proposals=(PROPOSAL,), refund=None):
    return lambda q, c, cust: {"record": {"outcome": outcome, "reason": reason, "steps": [1, 2], "error": ""}, "refund": refund,
                               "proposals": list(proposals)}


queued = []


def writer(proposal):
    queued.append(proposal)
    return "item-1"


def run(billing_fn, proposal_fn, **kw):
    return handle_message(MSG, answer, lambda r: "stand-in", lambda r, ms: None, triage, lambda p: "route-1", customer_id="cust_002",
                          billing_fn=billing_fn, privacy_fn=None, proposal_fn=proposal_fn, **kw)


# --- the switch ------------------------------------------------------------------------------------------------
old = os.environ.pop("HUMAN_GATE_QUEUE", None)
check(_default_proposal_queue() is None, "the queue write is off when HUMAN_GATE_QUEUE is not set")
for value in ("off", "true", "ON", "1", "shadow", ""):
    os.environ["HUMAN_GATE_QUEUE"] = value
    check(_default_proposal_queue() is None, f"HUMAN_GATE_QUEUE={value!r} is off: only the exact word on turns it on")
os.environ["HUMAN_GATE_QUEUE"] = "on"
check(_default_proposal_queue() is _default_route, "HUMAN_GATE_QUEUE=on uses the same writer as routing notes (the desk_service login)")
if old is None:
    del os.environ["HUMAN_GATE_QUEUE"]
else:
    os.environ["HUMAN_GATE_QUEUE"] = old

# --- the handler -----------------------------------------------------------------------------------------------
out = run(billing(), writer)
b = out["billing"]
check(queued == [PROPOSAL], "a queued proposal is put into the queue exactly as the agent made it")
check(b["proposal_queued"] is True and b["proposal_item_id"] == "item-1" and b["proposal_error"] == "", "and the result records that and the item id")
check(out["answer"] == "the reply" and out["behavior"] == "answer", "the customer's reply is not changed")
check(b["would_refund"] is False, "and no refund is recorded: the queue write only records what a person must decide")

queued.clear()
out = run(billing(), None)
check(queued == [] and out["billing"]["proposal_queued"] is False, "with the switch off nothing is queued, even when billing proposes")
check(out["billing"]["would_queue"] is True, "and shadow still says it would have queued")

for outcome, reason in (("refused", "not_eligible"), ("needs_person", "missing_details"), ("needs_person", "needs_evidence")):
    queued.clear()
    out = run(billing(outcome, reason, proposals=()), writer)
    check(queued == [] and out["billing"]["proposal_queued"] is False, f"{outcome}/{reason}: nothing to queue")
queued.clear()
out = run(billing("settled", "", proposals=(), refund={"status": "done", "amount": "19.00", "currency": "EUR", "order_id": "ord_1001"}), writer)
check(queued == [] and out["billing"]["would_refund"] is True, "a settled shadow refund is not a proposal and queues nothing")
queued.clear()
out = run(billing("needs_person", "needs_evidence", proposals=(PROPOSAL,)), writer)
check(queued == [], "a proposal is queued only when the outcome is queued")

two = {**PROPOSAL, "case_id": CASE, "tool": "issue_refund"}
queued.clear()
out = run(billing(proposals=(PROPOSAL, two)), writer)
check(len(queued) == 2 and out["billing"]["proposal_item_id"] == "item-1", "every proposal is queued, none dropped silently")


def failing(proposal):
    raise RuntimeError("could not connect to postgresql://desk_service:secret@host")


out = run(billing(), failing)
b = out["billing"]
check(b["proposal_queued"] is False and b["proposal_error"] == "RuntimeError" and "secret" not in str(b), "a failing queue write is recorded by class name only")
check(out["answer"] == "the reply" and b["would_queue"] is True and b["error"] == "", "and the reply and the billing outcome are untouched")

calls = []


def writer_after_error(proposal):
    calls.append(proposal)
    raise ValueError("x")


run(billing(proposals=(PROPOSAL, two)), writer_after_error)
check(len(calls) == 1, "after a failure the handler stops writing")

out = run(lambda q, c, cust: {"record": "not a dict"}, writer)
check(out["billing"]["error"] != "" and out["answer"] == "the reply", "a malformed billing result is an error and queues nothing")

out = handle_message(MSG, answer, lambda r: "stand-in", lambda r, ms: None, triage, lambda p: "route-1", customer_id="cust_002")
check(out["billing"]["proposal_queued"] is False, "the old call with no new arguments queues nothing")

# --- the trace -------------------------------------------------------------------------------------------------
exporter = InMemorySpanExporter()
client = tracing.make_client(public_key="pk-lf-test", secret_key="sk-lf-test", base_url="http://localhost:9", span_exporter=exporter)
base = {"case_id": "case_20261128_0123456789ab", "question": MSG, "answer": "a", "label": "normal", "behavior": "answer", "route": "vector",
        "citations": [], "sources": [], "attempts": 1, "refusal_reason": "", "handoff": {"needed": False, "reason": ""},
        "review": {"needed": False, "queued": False, "error": ""}}
tracing.record_case({**base, "billing": {"ran": True, "outcome": "queued", "reason": "over_cap", "steps": 2, "would_refund": False, "would_queue": True,
                                         "proposal_queued": True, "proposal_item_id": "1db066c7-fd3a-4560-8387-8ff421aefed0", "proposal_error": "", "error": ""}},
                    50, client=client)
client.flush()
blob = json.dumps([{"name": s.name, "attrs": {k: (v if isinstance(v, (str, int, float, bool)) else list(v)) for k, v in (s.attributes or {}).items()}}
                   for s in exporter.get_finished_spans()])
check("proposal_queued" in blob and "billing_proposal_queued" in blob, "the trace says whether the proposal was queued")
check("1db066c7" not in blob and "540.00" not in blob and "ord_2001" not in blob and "cust_002" not in blob, "and carries no item id, message, amount, order or customer")

print(f"HUMAN GATE HANDLER TESTS: {n} checks passed")
