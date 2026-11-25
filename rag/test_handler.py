"""Offline tests for the handler. Run from the rag folder: uv run python test_handler.py"""
import re

from desk_logic import HOSTILE_REPLY, QUEUE_FAILED_REPLY
import tracing
tracing.use_client(None)  # no real traces from tests
from handler import handle_message

n = 0
PROMISE = re.compile(r"\b(we|i)\s*(will|'ll)\s+(refund|pay|compensate|reimburse|credit)\b|"
                     r"\byou\s+will\s+(get|receive)\b|\bguarantee\b|\bi\s+promise\b", re.I)


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


def result(behavior, needed, reason="", answer="reply"):
    return {"question": "q", "case_id": "case_20261125_aaaaaaaaaaaa", "behavior": behavior,
            "answer": answer, "handoff": {"needed": needed, "reason": reason}}


calls = []


def fake_enqueue(r):
    calls.append(r["case_id"])
    return "11111111-1111-1111-1111-111111111111"


def broken_enqueue(r):
    raise RuntimeError("could not connect to postgresql://user:secret@host")


check("the queue-failed reply makes no promise", not PROMISE.search(QUEUE_FAILED_REPLY))
check("the queue-failed reply does not claim a review was marked", "marking" not in QUEUE_FAILED_REPLY)

out = handle_message("q", lambda q: result("answer", False), fake_enqueue)
check("a normal answer is not queued", calls == [] and out["review"]["queued"] is False and out["review"]["needed"] is False)

out = handle_message("q", lambda q: result("escalate", True, "hostile", HOSTILE_REPLY), fake_enqueue)
check("a hostile message is queued once", calls == ["case_20261125_aaaaaaaaaaaa"])
check("the result records the item", out["review"]["queued"] and out["review"]["item_id"].startswith("1111"))
check("the hostile reply is kept when queued", out["answer"] == HOSTILE_REPLY)

out = handle_message("q", lambda q: result("escalate", True, "hostile", HOSTILE_REPLY), broken_enqueue)
check("a failed queue write is recorded", out["review"]["queued"] is False and out["review"]["error"] == "RuntimeError")
check("the error text is not kept", "secret" not in str(out["review"]))
check("the reply no longer promises a review", out["answer"] == QUEUE_FAILED_REPLY)
check("the handoff is still marked as needed", out["handoff"]["needed"] is True)

out = handle_message("q", lambda q: result("refuse", True, "verification_failed", "NOT_FOUND"), fake_enqueue)
check("a failed-verification refusal is queued", out["review"]["queued"] and calls[-1] == "case_20261125_aaaaaaaaaaaa")
out = handle_message("q", lambda q: result("refuse", True, "verification_failed", "NOT_FOUND"), broken_enqueue)
check("a refusal keeps its own reply when the queue fails", out["answer"] == "NOT_FOUND")
print(f"\n{n} checks passed")
