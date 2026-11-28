"""Offline tests for privacy in shadow mode: the shadow run, the handler hook, the trace. No model, no database."""
import json
import os

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import tracing
tracing.use_client(None)  # no real traces from tests
import privacy_reply as pr
from handler import handle_message
from privacy_shadow import default_privacy_fn, shadow_privacy
from privacy_fakes import make   # the fake connection and fake privacy code, shared with the scorer tests

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


CASE = "case_20261128_aaaaaaaaaaaa"
MSG = "Please delete my account. My email is secret.person@example.com and my card is 4417."


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class Reply:
    def __init__(self, *blocks, stop="tool_use"):
        self.content, self.stop_reason = list(blocks), stop


def model_calling(name):
    sent = []

    def create(**kw):
        sent.append(kw)
        if len(sent) == 1:
            return Reply(Block(type="tool_use", id="tu_1", name=name, input={}))
        return Reply(stop="end_turn")
    return create


# --- the shadow run ----------------------------------------------------------------------------------------------
tools, db, conns = make()
out = shadow_privacy(MSG, CASE, "cust_001", tools, create_fn=model_calling("request_account_deletion"))
check(out["record"]["outcome"] == "requested" and out["record"]["kind"] == "deletion", "a deletion request is run in shadow")
check(out["effects"] == [{"change": "opened", "kind": "deletion", "customer_id": "cust_001"}], "and the effect is read from the tables")
check(out["calls"] == [("request_account_deletion", "cust_001")], "the call used the caller's customer id")
check(db == [] and conns[-1].rolled and conns[-1].closed, "the database is rolled back: shadow keeps nothing")

out = shadow_privacy("how long does deletion take?", CASE, "cust_001", tools,
                     create_fn=lambda **kw: Reply(Block(type="tool_use", id="t", name="close_case",
                                                         input={"outcome": "needs_person", "reason": "unclear_request"})))
check(out["record"]["outcome"] == "needs_person" and out["effects"] == [] and out["calls"] == [], "a question opens nothing")


def failing(**kw):
    raise RuntimeError("down")


out = shadow_privacy(MSG, CASE, "cust_001", tools, create_fn=failing)
check(out["record"]["outcome"] == "needs_person" and out["record"]["reason"] == "model_error" and out["effects"] == [], "a failing model is a hand-off with no effect")
check(db == [] and conns[-1].rolled, "and still nothing is kept")

# --- the switch -----------------------------------------------------------------------------------------------------
old = os.environ.pop("PRIVACY_MODE", None)
check(default_privacy_fn() is None, "shadow mode is off when PRIVACY_MODE is not set")
for value in ("off", "live", "SHADOW", "1", ""):
    os.environ["PRIVACY_MODE"] = value
    check(default_privacy_fn() is None, f"PRIVACY_MODE={value!r} is off: only the exact word shadow turns it on")
os.environ["PRIVACY_MODE"] = "shadow"
check(callable(default_privacy_fn()), "PRIVACY_MODE=shadow gives a function")
if old is None:
    del os.environ["PRIVACY_MODE"]
else:
    os.environ["PRIVACY_MODE"] = old

# --- the handler hook ----------------------------------------------------------------------------------------------


def answer(label="normal", reply="the reply"):
    return lambda q: {"question": q, "case_id": CASE, "label": label, "behavior": "answer", "answer": reply,
                      "handoff": {"needed": False, "reason": ""}}


def tri(intent="privacy", fallback=False):
    base = {"intent": intent, "confidence": 0.9, "order_id": None, "amount": None, "currency": None,
            "days_since_purchase": None, "dropped_facts": [], "fallback": fallback, "fallback_reason": ""}
    return lambda q: base


def route(p):
    return "route-1"


def no_enqueue(r):
    raise AssertionError("the answer queue must not be used here")


calls = []
OPENED = [{"change": "opened", "kind": "deletion", "customer_id": "cust_001"}]


def privacy_ok(q, case_id, customer_id):
    calls.append((q, case_id, customer_id))
    return {"record": {"outcome": "requested", "reason": "", "kind": "deletion", "request_id": "1db066c7-fd3a-4560-8387-8ff421aefed0",
                       "steps": [1], "error": ""}, "effects": OPENED, "calls": []}


def run(privacy_fn, customer_id="cust_001", triage_fn=None, label="normal"):
    return handle_message(MSG, answer(label), no_enqueue, lambda r, ms: None, triage_fn or tri(), route,
                          customer_id=customer_id, billing_fn=None, privacy_fn=privacy_fn)


out = run(privacy_ok)
p = out["privacy"]
check(p["ran"] and p["mode"] == "shadow" and p["outcome"] == "requested" and p["kind"] == "deletion" and p["steps"] == 1,
      "a privacy message with a customer id runs privacy in shadow")
check(p["would_open"] is True and p["would_cancel"] is False, "and says a request would have been opened, as read from the effects")
check(p["preview"] == pr.OPENED_DELETION, "and keeps a preview of the words, built by code")
check(calls == [(MSG, CASE, "cust_001")], "privacy got the message, the case id and the caller's customer id")
check(out["answer"] == "the reply" and out["behavior"] == "answer", "the customer's reply is not changed")
check(out["review"]["queued"] is False, "the answer review queue is not touched")

for label_ in ("vague", "hostile"):
    calls.clear()
    out = run(privacy_ok, label=label_)
    check(out["privacy"]["ran"] is False and out["privacy"]["skipped"] == "not_privacy" and calls == [], f"a {label_} message does not run privacy")
calls.clear()
for intent in ("refund", "policy_question", "subscription"):
    out = run(privacy_ok, triage_fn=tri(intent))
    check(out["privacy"]["skipped"] == "not_privacy" and calls == [], f"a {intent} message does not run privacy")
out = run(privacy_ok, triage_fn=tri(fallback=True))
check(out["privacy"]["skipped"] == "not_privacy" and calls == [], "a triage fallback does not run privacy")

for bad in (None, "", "cust_1", "cust_0011", "cust_002; drop", "CUST_001", 5, "cust_001\n"):
    calls.clear()
    out = run(privacy_ok, customer_id=bad)
    check(out["privacy"]["ran"] is False and out["privacy"]["skipped"] == "no_customer" and calls == [], f"no usable customer id {bad!r}: privacy does not run")

calls.clear()
out = handle_message(MSG, answer(), no_enqueue, lambda r, ms: None, tri(), route)   # the old call, with no privacy argument
check(out["privacy"]["skipped"] == "off" and out["privacy"]["mode"] == "off", "with shadow mode off the result says so")


def boom(q, c, cust):
    raise RuntimeError("could not connect to postgresql://user:secret@host")


out = run(boom)
check(out["privacy"]["ran"] is False and out["privacy"]["error"] == "RuntimeError" and "secret" not in str(out["privacy"]), "a failing shadow run is recorded by class name only")
check(out["answer"] == "the reply", "a failing shadow run leaves the reply alone")


def odd(q, c, cust):
    return {"record": "not a dict"}


check(run(odd)["privacy"]["error"] != "" and run(odd)["answer"] == "the reply", "a malformed result is an error and changes nothing")

out = run(lambda q, c, cust: {"record": {"outcome": "needs_person", "reason": "tool_error", "steps": [1], "error": ""}, "effects": []})
check(out["privacy"]["preview"] == pr.UNCLEAR and out["privacy"]["would_open"] is False, "a tool fault previews words that promise nothing")
out = run(lambda q, c, cust: {"record": {"outcome": "cancelled", "reason": "", "kind": "deletion", "request_id": "1db066c7-fd3a-4560-8387-8ff421aefed0",
                                         "steps": [1], "error": ""},
                              "effects": [{"change": "cancelled", "kind": "deletion", "customer_id": "cust_001"}]})
check(out["privacy"]["would_cancel"] is True and out["privacy"]["would_open"] is False, "a cancel is recorded as would-cancel")
out = run(lambda q, c, cust: {"record": {"outcome": "requested", "reason": "", "kind": "deletion", "request_id": "1db066c7-fd3a-4560-8387-8ff421aefed0",
                                         "steps": [1], "error": ""}, "effects": []})
check(out["privacy"]["would_open"] is False, "would-open comes from the effects, not from what the agent said")

# --- the trace -------------------------------------------------------------------------------------------------------
exporter = InMemorySpanExporter()
client = tracing.make_client(public_key="pk-lf-test", secret_key="sk-lf-test", base_url="http://localhost:9", span_exporter=exporter)


def spans():
    client.flush()
    return [{"name": s.name, "attrs": {k: (v if isinstance(v, (str, int, float, bool)) else list(v)) for k, v in (s.attributes or {}).items()}}
            for s in exporter.get_finished_spans()]


base = {"case_id": "case_20261128_0123456789ab", "question": MSG, "answer": "a", "label": "normal", "behavior": "answer", "route": "vector",
        "citations": [], "sources": [], "attempts": 1, "refusal_reason": "", "handoff": {"needed": False, "reason": ""},
        "review": {"needed": False, "queued": False, "error": ""}}
exporter.clear()
traced = {**base, "privacy": {"ran": True, "mode": "shadow", "skipped": "", "outcome": "requested", "reason": "", "kind": "deletion", "steps": 1,
                              "would_open": True, "would_cancel": False, "preview": pr.OPENED_DELETION, "error": ""}}
tracing.record_case(traced, 50, client=client)
sp = spans()
blob = json.dumps(sp)
check(any(s["name"] == "privacy_shadow" for s in sp), "a privacy_shadow span is exported when privacy ran")
check("requested" in blob and "would_open" in blob and "deletion" in blob, "the outcome, the kind and the would-open flag are in the trace")
check("secret.person" not in blob and "4417" not in blob and "cust_001" not in blob, "the message, the email and the customer id are NOT in the trace")
check("I have opened a request" not in blob, "the preview words are not in the trace either")
exporter.clear()
tracing.record_case({**base, "case_id": "case_20261128_0123456789ac", "privacy": {"ran": False, "skipped": "off"}}, 5, client=client)
check(not any(s["name"] == "privacy_shadow" for s in spans()), "no privacy span when privacy did not run")
exporter.clear()
check(tracing.record_case({**base, "case_id": "case_20261128_0123456789ad"}, 5, client=client) is not None, "a result with no privacy key still traces")

print(f"PRIVACY SHADOW TESTS: {n} checks passed")
