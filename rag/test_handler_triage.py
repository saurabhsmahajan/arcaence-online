"""Offline tests for triage in the handler (shadow mode). Run from the rag folder."""
import tracing
tracing.use_client(None)  # no real traces from tests
from handler import handle_message

n = 0


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


CASE = "case_20261127_aaaaaaaaaaaa"


def answer(label="normal", behavior="answer", needed=False, reply="the reply"):
    return lambda q: {"question": q, "case_id": CASE, "label": label, "behavior": behavior, "answer": reply,
                      "handoff": {"needed": needed, "reason": "hostile" if needed else ""}}


def tri(intent="refund", fallback=False, dropped=(), **facts):
    base = {"intent": intent, "confidence": 0.9, "order_id": None, "amount": None, "currency": None,
            "days_since_purchase": None, "dropped_facts": list(dropped), "fallback": fallback,
            "fallback_reason": "error: X" if fallback else ""}
    base.update(facts)
    return lambda q: base


routed = []


def route_ok(proposal):
    routed.append(proposal)
    return "22222222-2222-2222-2222-222222222222"


def route_broken(proposal):
    raise RuntimeError("could not connect to postgresql://user:secret@host")


def boom(q):
    raise RuntimeError("triage exploded")


def no_enqueue(r):
    raise AssertionError("the answer queue must not be used here")


# a request for a specialist is queued as a routing note
out = handle_message("refund ord_1042", answer(), no_enqueue, lambda r, ms: None, tri(order_id="ord_1042"), route_ok)
t = out["triage"]
check("a refund request is routed to billing", t["ran"] and t["intent"] == "refund" and t["specialist"] == "billing")
check("the routing note is queued once", t["routing_queued"] is True and len(routed) == 1 and t["item_id"].startswith("2222"))
p = routed[0]
check("the note is a route_case proposed action for this case", p["tool"] == "route_case" and p["case_id"] == CASE)
check("the note carries the stated fact only", p["args"]["facts"] == {"order_id": "ord_1042"})
check("shadow mode leaves the reply unchanged", out["answer"] == "the reply" and out["behavior"] == "answer")
check("shadow mode does not touch the answer review", out["review"]["queued"] is False)

# a policy question is not routed
routed.clear()
out = handle_message("what is the policy", answer(), no_enqueue, lambda r, ms: None, tri("policy_question"), route_ok)
check("a policy question is not queued", routed == [] and out["triage"]["routing_queued"] is False)
check("a policy question still records the intent", out["triage"]["intent"] == "policy_question" and out["triage"]["specialist"] == "none")

# multi messages are triaged too
out = handle_message("two things", answer(label="multi"), no_enqueue, lambda r, ms: None, tri("subscription"), route_ok)
check("a multi message is triaged", out["triage"]["ran"] and out["triage"]["routing_queued"])

# other labels are skipped
for label in ("vague", "hostile"):
    routed.clear()
    seen = []
    out = handle_message("x", answer(label=label), lambda r: "id", lambda r, ms: None, lambda q: seen.append(q) or tri()(q), route_ok)
    check(f"a {label} message is not triaged", seen == [] and out["triage"]["ran"] is False and routed == [])

# a message with no label (older results) is skipped
out = handle_message("x", lambda q: {"question": q, "case_id": CASE, "behavior": "answer", "answer": "a",
                                     "handoff": {"needed": False, "reason": ""}}, no_enqueue, lambda r, ms: None, boom, route_ok)
check("no label means no triage", out["triage"]["ran"] is False and out["triage"]["error"] == "")

# a fallback routes nothing and says why
routed.clear()
out = handle_message("x", answer(), no_enqueue, lambda r, ms: None, tri(fallback=True), route_ok)
check("a triage fallback routes nothing", routed == [] and out["triage"]["fallback"] is True)
check("the fallback reason is kept", out["triage"]["fallback_reason"] == "error: X")

# dropped facts are recorded
out = handle_message("x", answer(), no_enqueue, lambda r, ms: None, tri(dropped=["order_id"]), route_ok)
check("dropped facts are recorded", out["triage"]["dropped_facts"] == ["order_id"])

# failures never touch the reply
out = handle_message("x", answer(), no_enqueue, lambda r, ms: None, tri(), route_broken)
check("a failed routing write is recorded by class", out["triage"]["routing_queued"] is False and out["triage"]["error"] == "RuntimeError")
check("the error text is not kept", "secret" not in str(out["triage"]))
check("a failed routing write leaves the reply alone", out["answer"] == "the reply")

out = handle_message("x", answer(), no_enqueue, lambda r, ms: None, boom, route_ok)
check("a triage crash is recorded and contained", out["triage"]["error"] == "RuntimeError" and out["answer"] == "the reply")
check("the crash text is not kept", "exploded" not in str(out["triage"]))

# the answer-review path still works beside triage
sent = []
out = handle_message("x", answer(label="hostile", behavior="escalate", needed=True, reply="fixed"),
                     lambda r: sent.append(r["case_id"]) or "id", lambda r, ms: None, boom, route_ok)
check("a hostile case is still queued for review", sent == [CASE] and out["review"]["queued"] is True)

print(f"\n{n} checks passed")
