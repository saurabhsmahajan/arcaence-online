"""Offline tests for desk_scoring. Run from the rag folder: uv run python test_desk_scoring.py"""
from desk_scoring import PROMISE, expected_pairs, gate, score_deterministic, summarize

P = {"01": "tos_v3", "06": "schedule_ab_v3", "02": "tos_v2", "05": "draft"}
C = lambda d, c: {"doc_id": d, "clause_id": c}
n = 0


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


def q(exp, src="01_terms_of_service_v3.md s2.2"):
    return {"expected_behavior": exp, "authoritative_source": src}


def res(behavior, answer="x", cites=(), problems=(), handoff=False):
    return {"behavior": behavior, "answer": answer, "citations": list(cites),
            "problems": list(problems), "handoff": {"needed": handoff}}


sc = lambda qq, rr, forb=frozenset(): score_deterministic(qq, rr, forb, P)

check("pairs: clauses with file prefix",
      expected_pairs("01_terms_of_service_v3.md s2.2, s2.3", P) == {("tos_v3", "2.2"), ("tos_v3", "2.3")})
check("pairs: two segments, schedule has no clause",
      expected_pairs("01_terms_of_service_v3.md s3.4; 06_schedule_a_b_fees_and_disputes_v3.pdf Schedule A", P)
      == {("tos_v3", "3.4")})
check("pairs: 'none' gives nothing", expected_pairs("none", P) == set())

check("clarify passes with one question", sc(q("clarify"), res("clarify", "Which one?"))["pass_det"])
check("clarify fails with two questions", not sc(q("clarify"), res("clarify", "Which? Why?"))["pass_det"])
check("clarify fails when it answered", not sc(q("clarify"), res("answer", "Yes."))["pass_det"])
check("clarify fails with a citation",
      not sc(q("clarify"), res("clarify", "Which?", [C("tos_v3", "2.2")]))["pass_det"])

check("escalate passes", sc(q("escalate"), res("escalate", "A person will look.", handoff=True))["pass_det"])
check("escalate fails without handoff", not sc(q("escalate"), res("escalate", "ok"))["pass_det"])
r = sc(q("escalate"), res("escalate", "We will refund you today.", handoff=True))
check("escalate fails on a promise and flags U4", not r["pass_det"] and any("U4" in u for u in r["unsupported"]))
check("escalate that answered normally fails", not sc(q("escalate"), res("answer", "Ok."))["pass_det"])

good = res("partial", "x", [C("tos_v3", "2.2")])
check("partial passes with expected clause", sc(q("partial"), good)["pass_det"])
check("partial fails with wrong clause", not sc(q("partial"), res("partial", "x", [C("tos_v3", "5.3")]))["pass_det"])
check("partial fails when same clause number but other document",
      not sc(q("partial"), res("partial", "x", [C("tos_v2", "2.2")]))["pass_det"])
r = sc(q("partial"), res("answer", "x", [C("tos_v3", "2.2")]))
check("partial answered fully flags U3", not r["pass_det"] and any("U3" in u for u in r["unsupported"]))

r = sc(q("answer"), res("answer", "x", [C("tos_v2", "2.2")]), forb={"tos_v2"})
check("forbidden cite flags U1 and fails", not r["pass_det"] and any("U1" in u for u in r["unsupported"]))
r = sc(q("answer"), res("answer", "x", [C("tos_v3", "2.2")], problems=["bad"]))
check("verifier problem flags U2", any("U2" in u for u in r["unsupported"]))
check("refuse passes", sc(q("refuse"), res("refuse", "NOT_FOUND"))["pass_det"])

rows = [{"expected": "partial", "passed": True, "unsupported": []},
        {"expected": "partial", "passed": False, "unsupported": ["U3"]},
        {"expected": "clarify", "passed": True, "unsupported": []},
        {"expected": "clarify", "passed": True, "unsupported": []}]
s = summarize(rows)
check("summary counts", s["rows"] == 4 and s["unsupported"] == 1 and s["unsupported_rate"] == 0.25)
check("summary by behaviour", s["by_behavior"] == {"clarify": "2/2", "partial": "1/2"})
check("gate: equal passes", gate({"unsupported_rate": 0.1}, {"unsupported_rate": 0.1})[0])
check("gate: lower passes", gate({"unsupported_rate": 0.05}, {"unsupported_rate": 0.1})[0])
check("gate: rise fails", not gate({"unsupported_rate": 0.12}, {"unsupported_rate": 0.1})[0])
check("U4 ignores a restated reply time",
      not PROMISE.search("You will receive a reply within 5 working days."))
check("U4 still catches a refund promise", bool(PROMISE.search("You will receive a full refund.")))
check("U4 still catches 'you will get your money'", bool(PROMISE.search("You will get your money back.")))
print(f"\nALL {n} CHECKS PASS")
