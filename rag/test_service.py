"""Offline tests for the service. Run from the rag folder: uv run python test_service.py
Uses a fake desk, so it makes no model calls and touches no database."""
import threading

from fastapi.testclient import TestClient

from limits import DailyCap, TokenBucket
from service import create_app, parse_keys

n = 0
KEY = "web-key-0123456789"
OTHER = "agent-key-0123456789"


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


def fake(message):
    return {"case_id": "case_20261125_aaaaaaaaaaaa", "behavior": "answer", "answer": "reply",
            "citations": [{"doc_id": "tos_v3", "clause_id": "2.2"}], "question": message,
            "sources": ["tos_v3 2.2"], "attempt_log": [{"raw": "internal"}], "classifier_note": "internal",
            "review": {"needed": False, "queued": False, "item_id": None, "error": ""}}


def app(**kw):
    kw.setdefault("handle", fake)
    kw.setdefault("keys", {"web": KEY, "agent": OTHER})
    kw.setdefault("limiter", TokenBucket(60, 100))
    kw.setdefault("cap", DailyCap(1000))
    return TestClient(create_app(**kw))


H = {"X-API-Key": KEY}
post = lambda c, msg="hello", h=H: c.post("/v1/messages", json={"message": msg}, headers=h)

# --- limits, with a fake clock
t = [0.0]
b = TokenBucket(60, 3, clock=lambda: t[0])
check("a client may burst up to the limit", [b.allow("a")[0] for _ in range(3)] == [True, True, True])
ok, wait = b.allow("a")
check("the next request is refused with a wait time", ok is False and wait >= 1)
check("another client is not affected", b.allow("b")[0] is True)
t[0] += 2
check("tokens come back with time", b.allow("a")[0] is True)
d = [1]
cap = DailyCap(2, today=lambda: d[0])
check("the daily cap allows its limit", cap.take() and cap.take())
check("and then refuses", cap.take() is False)
d[0] = 2
check("a new day starts again", cap.take() is True)

# --- keys
check("keys parse", parse_keys("web=abcdefghijklmnop, agent=0123456789abcdef") ==
      {"web": "abcdefghijklmnop", "agent": "0123456789abcdef"})
for bad in ("web", "web=short", "=abcdefghijklmnop"):
    try:
        parse_keys(bad)
        check(f"a bad key setting is refused: {bad}", False)
    except ValueError:
        check(f"a bad key setting is refused: {bad}", True)
try:
    create_app(handle=fake, keys={})
    check("the service will not start without keys", False)
except RuntimeError:
    check("the service will not start without keys", True)

# --- requests
c = app()
check("healthz needs no key", c.get("/healthz").json() == {"status": "ok"})
check("no key is refused", post(c, h={}).status_code == 401)
check("a wrong key is refused", post(c, h={"X-API-Key": "wrong-key-0123456789"}).status_code == 401)
check("a key that only starts like a real one is refused", post(c, h={"X-API-Key": KEY[:-1]}).status_code == 401)
r = post(c)
check("a valid request works", r.status_code == 200)
check("the reply has only the public fields",
      set(r.json()) == {"case_id", "behavior", "answer", "citations", "needs_person"})
check("citations are labels", r.json()["citations"] == ["tos_v3 2.2"])
check("nothing internal leaks", "internal" not in r.text and "sources" not in r.text)
check("the other key works too", post(c, h={"X-API-Key": OTHER}).status_code == 200)
check("an empty message is refused", post(c, "").status_code == 422)
check("a message over 2000 characters is refused", post(c, "x" * 2001).status_code == 422)
bad = c.post("/v1/messages", json={"message": "x" * 2001}, headers=H)
check("a refused message is not echoed back", "xxxx" not in bad.text)
check("a body that is not JSON is refused", c.post("/v1/messages", content="hi", headers=H).status_code == 422)
check("docs are not exposed", c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404)

# --- rate limit, cap, busy, failure
c = app(limiter=TokenBucket(6, 2))
codes = [post(c).status_code for _ in range(3)]
check("the third request in a burst of two is refused", codes == [200, 200, 429])
check("a refusal says when to retry", post(c).headers.get("retry-after", "").isdigit())
check("the other client is not limited", post(c, h={"X-API-Key": OTHER}).status_code == 200)

c = app(cap=DailyCap(2))
check("the daily cap stops the service", [post(c).status_code for _ in range(3)] == [200, 200, 503])

c = app(cap=DailyCap(2))
post(c, h={})  # an unauthorised call must not use up the cap
post(c, h={"X-API-Key": "wrong-key-0123456789"})
check("refused keys do not use the daily cap", [post(c).status_code for _ in range(2)] == [200, 200])


def boom(message):
    raise RuntimeError("could not connect to postgresql://user:secret@host")


c = app(handle=boom)
r = post(c)
check("a desk failure is a plain 500", r.status_code == 500 and r.json() == {"detail": "the service could not answer"})
check("the error text is not returned", "secret" not in r.text)

gate, started = threading.Event(), threading.Event()


def slow(message):
    started.set()
    gate.wait(5)
    return fake(message)


c = app(handle=slow, max_concurrent=1)
first = threading.Thread(target=lambda: post(c))
first.start()
started.wait(5)
check("a request over the concurrency limit is refused", post(c).status_code == 503)
gate.set()
first.join()
check("and it works again afterwards", post(c).status_code == 200)
print(f"\n{n} checks passed")
