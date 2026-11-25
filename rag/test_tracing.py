"""Offline tests for tracing. Run from the rag folder: uv run python test_tracing.py

No network: spans go to an in-memory exporter, so we can read exactly what would be sent.
"""
import json

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import tracing

n = 0


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


QUESTION = "My card ending 4417 was charged twice, I will call my lawyer tomorrow, Rahul Verma"
ANSWER = "Here is a long private answer about the refund of the second charge on the card."

exporter = InMemorySpanExporter()
client = tracing.make_client(public_key="pk-lf-test", secret_key="sk-lf-test",
                             base_url="http://localhost:9", span_exporter=exporter)


def spans_text():
    client.flush()
    out = []
    for s in exporter.get_finished_spans():
        out.append({"name": s.name, "attrs": {k: (v if isinstance(v, (str, int, float, bool)) else list(v))
                                              for k, v in (s.attributes or {}).items()}})
    return out


result = {
    "case_id": "case_20261125_abcdef012345", "question": QUESTION, "answer": ANSWER,
    "label": "normal", "classifier_confidence": "high", "classifier_note": "",
    "behavior": "answer", "route": "vector",
    "citations": [{"doc_id": "tos_v3", "clause_id": "3.2"}, {"doc_id": "tos_v3", "clause_id": "3.3"}],
    "sources": ["tos_v3 3.2", "tos_v3 3.3"], "attempts": 1, "refusal_reason": "",
    "attempt_log": [{"raw": ANSWER, "problems": [QUESTION]}],
    "handoff": {"needed": False, "reason": ""}, "review": {"needed": False, "queued": False, "error": ""},
}

# --- the mask itself
check("text keys are replaced", tracing.mask(data={"answer": "x", "label": "normal"})
      == {"answer": "[not recorded]", "label": "normal"})
check("nested text keys are replaced", tracing.mask(data={"a": [{"question": "x"}]})["a"][0]["question"] == "[not recorded]")
check("long strings are cut", tracing.mask(data="x" * 500).startswith("[not recorded]"))
check("short strings stay", tracing.mask(data="tos_v3 3.2") == "tos_v3 3.2")

# --- the hard stop: even short text passed as input or output never leaves
exporter.clear()
with client.start_as_current_observation(name="leak_probe", as_type="span", input="my secret question",
                                         output="secret answer", metadata={"answer": "LEAK-ME"}):
    pass
blob = json.dumps(spans_text())
check("short input text is dropped at export", "secret question" not in blob)
check("short output text is dropped at export", "secret answer" not in blob)
check("a text key in metadata is masked", "LEAK-ME" not in blob)
exporter.clear()

# --- a normal case
tid = tracing.record_case(result, 1234, client=client)
check("returns a trace id", isinstance(tid, str) and len(tid) == 32)
check("trace id comes from the case id", tid == client.create_trace_id(seed=result["case_id"]))
spans = spans_text()
blob = json.dumps(spans)
check("spans were exported", len(spans) >= 2)
check("root span is named desk_message", any(s["name"] == "desk_message" for s in spans))
check("case id is in the trace", result["case_id"] in blob)
check("citation labels are in the trace", "tos_v3 3.2" in blob)
check("citations are labels, not dict text", "doc_id" not in blob)
check("latency is in the trace", "1234" in blob)
check("the customer's message is NOT in the trace", "4417" not in blob and "Rahul" not in blob and "lawyer" not in blob)
check("the answer text is NOT in the trace", "private answer" not in blob)
check("the raw model output / verifier text is NOT in the trace", "attempt_log" not in blob)

# --- a hostile case that was not queued
exporter.clear()
bad = dict(result, case_id="case_20261125_000000000001", behavior="escalate", route="none", citations=[],
           sources=[], attempts=0, handoff={"needed": True, "reason": "hostile"},
           review={"needed": True, "queued": False, "error": "OperationalError"})
tracing.record_case(bad, 50, client=client)
blob = json.dumps(spans_text())
check("unqueued handoff is visible", "OperationalError" in blob)
check("no message text for the hostile case either", "lawyer" not in blob and "4417" not in blob)

# --- fail open
class Broken:
    def create_trace_id(self, **_):
        raise RuntimeError("boom: secret detail")
check("a broken client returns None", tracing.record_case(result, 1, client=Broken()) is None)
check("a malformed result returns None", tracing.record_case({}, 1, client=client) is None)
tracing.use_client(None)
check("with tracing off, nothing happens", tracing.record_case(result, 1) is None)
tracing.flush()
check("flush with no client does not raise", True)

# --- the handler: tracing can never change the reply
from handler import handle_message


def fake_answer(q):
    return {"question": q, "case_id": "case_20261125_abcdef012345", "behavior": "answer", "answer": "fine reply",
            "handoff": {"needed": False, "reason": ""}}


def exploding_trace(r, ms):
    raise RuntimeError("tracing is down")


got = handle_message("hello", answer_fn=fake_answer, trace_fn=exploding_trace)
check("a tracing failure does not change the reply", got["answer"] == "fine reply")
seen = []
handle_message("hello", answer_fn=fake_answer, trace_fn=lambda r, ms: seen.append((r["case_id"], ms)))
check("the handler passes the case and a latency to tracing", len(seen) == 1 and isinstance(seen[0][1], int))

print(f"\nTRACING TESTS: {n} checks passed")
