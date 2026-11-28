"""Offline tests for desk_safe. Run from the rag folder: uv run python test_desk_safe.py"""
import os
import re
import time

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://none")

import desk_safe as ds

n = 0


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


def exc_in(module, name="Boom", text="x"):
    return type(name, (Exception,), {"__module__": module})(text)


# reasons come from the kind of exception, never its text
check("anthropic error is a model error", ds.fault_reason(exc_in("anthropic")) == "model_error")
check("http error is a model error", ds.fault_reason(exc_in("httpx._exceptions")) == "model_error")
check("psycopg error is a retrieval error", ds.fault_reason(exc_in("psycopg.errors")) == "retrieval_error")
check("anything else is unexpected", ds.fault_reason(KeyError("k")) == "unexpected_error")

# the deadline
check("a fast call returns its value", ds.run_with_deadline(lambda q: q + "!", 1.0, "a") == "a!")
t0 = time.perf_counter()
try:
    ds.run_with_deadline(lambda q: time.sleep(1.0), 0.2, "a")
    gave_up = False
except ds.concurrent.futures.TimeoutError:
    gave_up = True
check("a slow call is given up on", gave_up and time.perf_counter() - t0 < 0.9)
check("deadline: argument wins", ds.deadline_seconds(5) == 5.0)
check("deadline: bad value uses the default", ds.deadline_seconds("abc") == ds.DEFAULT_DEADLINE_S)
check("deadline: zero or negative uses the default",
      ds.deadline_seconds(0) == ds.DEFAULT_DEADLINE_S and ds.deadline_seconds(-3) == ds.DEFAULT_DEADLINE_S)
os.environ["DESK_DEADLINE_S"] = "7"
check("deadline: env is used when no argument", ds.deadline_seconds() == 7.0)
del os.environ["DESK_DEADLINE_S"]
check("deadline: default with nothing set", ds.deadline_seconds() == ds.DEFAULT_DEADLINE_S)

# the fault result
r = ds.fault_result("q", "timeout")
check("fault result has every key the handler reads", ds.well_formed(r))
check("fault result is a refusal with the fixed words",
      r["behavior"] == "refuse" and r["answer"] == ds.UNAVAILABLE_REPLY and r["refused"])
check("fault result asks for a person", r["handoff"] == {"needed": True, "reason": "unavailable_timeout"})
check("fault result carries no citations or sources", r["citations"] == [] and r["sources"] == [])

# the wrapper never raises
good = ds.fault_result("q", "timeout") | {"behavior": "answer", "answer": "ok [tos_v3 2.2]",
                                           "handoff": {"needed": False, "reason": ""}}
check("a good result passes through unchanged", ds.safe_desk_answer("q", lambda q: good) is good)


def boom(q):
    raise exc_in("anthropic", text="sk-secret ignore the rules")


out = ds.safe_desk_answer("q", boom)
check("a model fault gives the fixed reply", out["answer"] == ds.UNAVAILABLE_REPLY
      and out["refusal_reason"] == "unavailable_model_error")
check("the exception text is not in the result", "sk-secret" not in repr(out))
out = ds.safe_desk_answer("q", lambda q: time.sleep(0.8), deadline_s=0.2)
check("a hang gives a timeout", out["refusal_reason"] == "unavailable_timeout")
for bad in (None, "text", {"answer": "x"}, {**good, "handoff": "yes"}):
    check(f"bad result {type(bad).__name__} is unexpected_error",
          ds.safe_desk_answer("q", lambda q, b=bad: b)["refusal_reason"] == "unavailable_unexpected_error")

# the fixed sentences
WORDS = {"UNAVAILABLE": ds.UNAVAILABLE_REPLY, "NO_SOURCES": ds.NO_SOURCES_REPLY, "UNVERIFIED": ds.UNVERIFIED_REPLY}
PROMISE = re.compile(r"\b(we|i)\s*(will|'ll)\s+(refund|pay|compensate|reimburse|credit)\b|"
                     r"\byou\s+will\s+(get|receive)\b|\bguarantee\b|\bi\s+promise\b|\bdeleted\b|\bsent\b", re.I)
for name, text in WORDS.items():
    check(f"{name} reply makes no promise", not PROMISE.search(text))
    check(f"{name} reply has no digits and no brackets", not re.search(r"[\d\[\]]", text))
    check(f"{name} reply says it will not guess or points to a person",
          "guess" in text or "person" in text or "Help Centre" in text)
check("no reply is the literal NOT_FOUND", all(t != "NOT_FOUND" for t in WORDS.values()))

print(f"\n{n} checks passed")
