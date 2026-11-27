"""Offline tests for billing in shadow mode: the shadow run, the handler hook, the trace. No model, no database."""
import json
import os
from contextlib import contextmanager

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import tracing
tracing.use_client(None)  # no real traces from tests
import billing_reply as br
from billing_shadow import Queue, Watch, default_billing_fn, shadow_billing
from handler import handle_message

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


CASE = "case_20261127_aaaaaaaaaaaa"
MSG = "Refund 19.00 EUR on ord_1001 please. I am cust_002 and my card is 4417."


# --- the shadow run ----------------------------------------------------------------------------------------------
class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class Reply:
    def __init__(self, *blocks):
        self.content, self.stop_reason = list(blocks), "tool_use"


def use(i, name, **inp):
    return Block(type="tool_use", id=f"tu_{i}", name=name, input=inp)


ORDER = {"order_id": "ord_1001", "customer_id": "cust_001", "item": "Pro plan", "kind": "subscription", "amount": "19.00",
         "currency": "EUR", "purchased_at": "2026-11-01", "downloaded": False}


class Tools:
    def __init__(self, results):
        self.results, self.log, self.state = list(results), [], "closed"

    @contextmanager
    def case(self):
        self.state = "open"
        try:
            yield self
        finally:
            self.state = "rolled_back"

    def get_order(self, order_id):
        return ORDER

    def get_account(self, customer_id):
        return None

    def search_policy(self, query):
        return {"results": []}

    def issue_refund(self, customer_id, order_id, amount, clause_doc, clause_id, dry_run, confirm_token):
        self.log.append((customer_id, dry_run, self.state))
        return self.results.pop(0)


DONE = {"status": "done", "refund_id": "r1", "order_id": "ord_1001", "amount": "19.00", "currency": "EUR"}
script = [Reply(use(1, "get_order", order_id="ord_1001")),
          Reply(use(2, "request_refund", order_id="ord_1001", amount="19.00", clause_doc="tos_v3", clause_id="3.3"))]
t = Tools([{"status": "preview", "token": "tk"}, DONE])
out = shadow_billing(MSG, CASE, "cust_001", t, create_fn=lambda **kw: script.pop(0), today="2026-11-05")
check(out["record"]["outcome"] == "settled", "a shadow run returns the agent's record")
check(out["refund"] and out["refund"]["amount"] == "19.00" and out["refund"]["order_id"] == "ord_1001", "and the refund that would have been recorded")
check(t.log == [("cust_001", True, "open"), ("cust_001", False, "open")], "the customer id is the caller's, not the one in the message, and the money calls run inside the case")
check(t.state == "rolled_back", "the case is rolled back when the run ends")
check(out["proposals"] == [], "no proposal when none was made")

script = [Reply(use(1, "get_order", order_id="ord_1001")),
          Reply(use(2, "request_refund", order_id="ord_1001", amount="19.00", clause_doc="tos_v3", clause_id="3.3"))]
t = Tools([{"status": "preview", "token": "tk"}, {"status": "refused", "reason": "over_cap"}])
out = shadow_billing(MSG, CASE, "cust_001", t, create_fn=lambda **kw: script.pop(0), today="2026-11-05")
check(out["record"]["outcome"] == "queued" and out["refund"] is None, "an over-cap case is queued in memory and no refund is recorded")
check(len(out["proposals"]) == 1 and out["proposals"][0]["tool"] == "issue_refund", "the proposal is kept in memory, never sent anywhere")

# --- the switch ----------------------------------------------------------------------------------------------------
old = os.environ.pop("BILLING_MODE", None)
check(default_billing_fn() is None, "shadow mode is off when BILLING_MODE is not set")
for value in ("off", "live", "SHADOW", "1", ""):
    os.environ["BILLING_MODE"] = value
    check(default_billing_fn() is None, f"BILLING_MODE={value!r} is off: only the exact word shadow turns it on")
os.environ["BILLING_MODE"] = "shadow"
check(callable(default_billing_fn()), "BILLING_MODE=shadow gives a function")
if old is None:
    del os.environ["BILLING_MODE"]
else:
    os.environ["BILLING_MODE"] = old

# --- the handler hook ----------------------------------------------------------------------------------------------


def answer(label="normal", reply="the reply"):
    return lambda q: {"question": q, "case_id": CASE, "label": label, "behavior": "answer", "answer": reply,
                      "handoff": {"needed": False, "reason": ""}}


def tri(intent="refund", fallback=False):
    base = {"intent": intent, "confidence": 0.9, "order_id": None, "amount": None, "currency": None,
            "days_since_purchase": None, "dropped_facts": [], "fallback": fallback, "fallback_reason": ""}
    return lambda q: base


def route(p):
    return "route-1"


def no_enqueue(r):
    raise AssertionError("the answer queue must not be used here")


calls = []


def billing_ok(q, case_id, customer_id):
    calls.append((q, case_id, customer_id))
    return {"record": {"outcome": "settled", "reason": "", "steps": [1, 2, 3, 4], "error": ""}, "refund": DONE, "proposals": []}


def run(billing_fn, customer_id="cust_001", triage_fn=None, label="normal"):
    return handle_message(MSG, answer(label), no_enqueue, lambda r, ms: None, triage_fn or tri(), route,
                          customer_id=customer_id, billing_fn=billing_fn)


out = run(billing_ok)
b = out["billing"]
check(b["ran"] and b["mode"] == "shadow" and b["outcome"] == "settled" and b["steps"] == 4, "a refund message with a customer id runs billing in shadow")
check(b["would_refund"] is True and b["would_queue"] is False, "and says a refund would have been recorded")
check(b["preview"] == "Your refund of 19.00 EUR for order ord_1001 has been recorded.", "and keeps a preview of the words, built by code")
check(calls == [(MSG, CASE, "cust_001")], "billing got the message, the case id and the caller's customer id")
check(out["answer"] == "the reply" and out["behavior"] == "answer", "the customer's reply is not changed")
check(out["review"]["queued"] is False, "the answer review queue is not touched")

for label_ in ("vague", "hostile"):
    calls.clear()
    out = run(billing_ok, label=label_)
    check(out["billing"]["ran"] is False and out["billing"]["skipped"] == "not_refund" and calls == [], f"a {label_} message does not run billing")
calls.clear()
out = run(billing_ok, triage_fn=tri("policy_question"))
check(out["billing"]["skipped"] == "not_refund" and calls == [], "a policy question does not run billing")
out = run(billing_ok, triage_fn=tri("subscription"))
check(out["billing"]["skipped"] == "not_refund" and calls == [], "billing v1 handles refunds only: a subscription request does not run it")
out = run(billing_ok, triage_fn=tri(fallback=True))
check(out["billing"]["skipped"] == "not_refund" and calls == [], "a triage fallback does not run billing")

for bad in (None, "", "cust_1", "cust_0011", "cust_002; drop", "CUST_001", 5, "cust_001\n"):
    calls.clear()
    out = run(billing_ok, customer_id=bad)
    check(out["billing"]["ran"] is False and out["billing"]["skipped"] == "no_customer" and calls == [], f"no usable customer id {bad!r}: billing does not run")
check(calls == [], "a customer id written in the message is never used")

calls.clear()
out = handle_message(MSG, answer(), no_enqueue, lambda r, ms: None, tri(), route)   # the old call, with no billing arguments
check(out["billing"]["skipped"] == "off" and out["billing"]["mode"] == "off", "with shadow mode off the result says so")


def boom(q, c, cust):
    raise RuntimeError("could not connect to postgresql://user:secret@host")


out = run(boom)
check(out["billing"]["ran"] is False and out["billing"]["error"] == "RuntimeError" and "secret" not in str(out["billing"]), "a failing shadow run is recorded by class name only")
check(out["answer"] == "the reply", "a failing shadow run leaves the reply alone")


def odd(q, c, cust):
    return {"record": "not a dict"}


check(run(odd)["billing"]["error"] != "" and run(odd)["answer"] == "the reply", "a malformed result is an error and changes nothing")

out = run(lambda q, c, cust: {"record": {"outcome": "needs_person", "reason": "needs_evidence", "steps": [1], "error": ""}, "refund": None})
check(out["billing"]["preview"] == br.PERSON_QUEUED, "a preview for a case a person must handle says what the words would be if queued")

# --- the trace -------------------------------------------------------------------------------------------------------
exporter = InMemorySpanExporter()
client = tracing.make_client(public_key="pk-lf-test", secret_key="sk-lf-test", base_url="http://localhost:9", span_exporter=exporter)


def spans():
    client.flush()
    return [{"name": s.name, "attrs": {k: (v if isinstance(v, (str, int, float, bool)) else list(v)) for k, v in (s.attributes or {}).items()}}
            for s in exporter.get_finished_spans()]


base = {"case_id": "case_20261127_0123456789ab", "question": MSG, "answer": "a", "label": "normal", "behavior": "answer", "route": "vector",
        "citations": [], "sources": [], "attempts": 1, "refusal_reason": "", "handoff": {"needed": False, "reason": ""},
        "review": {"needed": False, "queued": False, "error": ""}}
exporter.clear()
traced = {**base, "billing": {"ran": True, "mode": "shadow", "skipped": "", "outcome": "settled", "reason": "", "steps": 4,
                              "would_refund": True, "would_queue": False, "preview": br.SETTLED_PLAIN, "error": ""}}
tracing.record_case(traced, 50, client=client)
sp = spans()
blob = json.dumps(sp)
check(any(s["name"] == "billing_shadow" for s in sp), "a billing_shadow span is exported when billing ran")
check("settled" in blob and "would_refund" in blob, "the outcome and the would-refund flag are in the trace")
check("4417" not in blob and "cust_002" not in blob and "ord_1001" not in blob and "19.00" not in blob, "the message, the customer id, the order and the amount are NOT in the trace")
check("has been recorded" not in blob, "the preview words are not in the trace either")
exporter.clear()
tracing.record_case({**base, "case_id": "case_20261127_0123456789ac", "billing": {"ran": False, "skipped": "off"}}, 5, client=client)
check(not any(s["name"] == "billing_shadow" for s in spans()), "no billing span when billing did not run")
exporter.clear()
check(tracing.record_case({**base, "case_id": "case_20261127_0123456789ad"}, 5, client=client) is not None, "a result with no billing key still traces")

# --- Watch and Queue ---------------------------------------------------------------------------------------------------
w = Watch(Tools([{"status": "preview", "token": "t"}, DONE]))
w.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", True, None)
check(w.commits == [], "a dry run is not a commit")
w.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", False, "t")
check(w.commits[0]["status"] == "done" and w.commits[0]["currency"] == "EUR", "a commit is noted with what the server said")
q = Queue()
check(q({"a": 1}) == 1 and q({"a": 2}) == 2, "the stand-in queue numbers what it keeps")

print(f"BILLING SHADOW TESTS: {n} checks passed")
