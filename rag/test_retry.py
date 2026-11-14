import json

import answer

LABELS = {"tos_v3 2.3"}


def reply(cites, refused=False):
    return {"answer": "Refunds get a reply within 5 working days.",
            "citations": [{"doc_id": d, "clause_id": c} for d, c in cites],
            "refused": refused, "refusal_reason": ""}


def run(replies):
    calls = []

    def stub(system, messages):
        calls.append(list(messages))
        r = replies.pop(0)
        return r, (json.dumps(r) if r is not None else "not json")

    answer.ask_structured = stub
    return answer.answer_with_retry("sys", "Sources: ...", LABELS), calls


bad = reply([("tos_v9", "7.7")])
good = reply([("tos_v3", "2.3")])

# A: bad first answer, good second answer
out, calls = run([bad, good])
assert out["attempts"] == 2 and not out["result"]["refused"], "A: should accept on attempt 2"
feedback = calls[1][-1]["content"]
assert "rejected by the verifier" in feedback and "tos_v9 7.7" in feedback, "A: feedback missing reasons"
print("A pass: retry fed the verifier's reason back, accepted on attempt 2")

# B: model never fixes it
out, calls = run([bad, bad, bad])
assert out["attempts"] == 3, "B: should stop after 1 try + 2 retries"
assert out["result"]["refused"] and out["result"]["refusal_reason"] == "verification_failed", "B: no safe fallback"
print("B pass: fell back to a safe refusal after 3 attempts")

# C: invalid JSON first, then good
out, calls = run([None, good])
assert out["attempts"] == 2 and not out["result"]["refused"], "C: should recover from bad JSON"
print("C pass: invalid JSON retried")

# D: a refusal is accepted straight away
out, calls = run([reply([], refused=True)])
assert out["attempts"] == 1 and out["result"]["refused"], "D: refusal should be accepted"
print("D pass: refusal accepted without retry")