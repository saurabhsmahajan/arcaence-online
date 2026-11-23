"""Offline tests for desk_logic. Run from the rag folder: uv run python test_desk_logic.py"""
import re
from desk_logic import (HOSTILE_REPLY, FALLBACK_CLARIFY, compose_parts, parts_problems)

lab = lambda c: f"{c['doc_id']} {c['clause_id']}".strip()
ok_check = lambda r, labels: []
bad_check = lambda r, labels: ["not among the sources it was given: [tos_v3 9.9]"]
C = lambda d, c: {"doc_id": d, "clause_id": c}
cov = lambda part, ans, *cs: {"part": part, "covered": True, "answer": ans, "citations": list(cs)}
unc = lambda part: {"part": part, "covered": False, "answer": "", "citations": []}
n = 0


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


# promise patterns the hostile reply must never contain (the scorer reuses the same idea)
PROMISE = re.compile(r"\b(we|i)\s*(will|'ll)\s+(refund|pay|compensate|reimburse|credit)\b|"
                     r"\byou\s+will\s+(get|receive)\b|\bguarantee\b|\bi\s+promise\b", re.I)
check("hostile reply makes no promise", not PROMISE.search(HOSTILE_REPLY))
check("hostile reply asks for a person", "person" in HOSTILE_REPLY)
check("clarify fallback is one question", FALLBACK_CLARIFY.count("?") == 1)

mixed = {"parts": [cov("refund window", "7 days.", C("tos_v3", "2.2")), unc("student discount")]}
check("mixed result passes", parts_problems(mixed, ok_check, set()) == [])
text, beh = compose_parts(mixed, lab)
check("mixed -> partial", beh == "partial")
check("covered part keeps its citation", "[tos_v3 2.2]" in text)
check("uncovered part uses fixed wording", "student discount" in text and "won't guess" in text)

allc = {"parts": [cov("a", "yes.", C("tos_v3", "3.4")), cov("b", "no.", C("tos_v3", "3.7"))]}
check("all covered -> answer", compose_parts(allc, lab)[1] == "answer")
allu = {"parts": [unc("a"), unc("b")]}
check("none covered -> refuse", compose_parts(allu, lab)[1] == "refuse")

check("empty parts rejected", parts_problems({"parts": []}, ok_check, set()) != [])
check("covered without citation rejected",
      parts_problems({"parts": [cov("a", "x.")]}, ok_check, set()) != [])
check("covered without answer rejected",
      parts_problems({"parts": [cov("a", "", C("tos_v3", "2.2"))]}, ok_check, set()) != [])
leak = {"parts": [{"part": "a", "covered": False, "answer": "maybe yes", "citations": []}]}
check("uncovered part may not carry an answer", parts_problems(leak, ok_check, set()) != [])
check("citation check is applied", parts_problems(mixed, bad_check, set()) != [])
print(f"\nALL {n} CHECKS PASS")
