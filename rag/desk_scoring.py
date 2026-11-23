"""Deterministic scoring for the desk pipeline. No API, database or network, so it tests offline.

Rules (written before the first run):
  clarify   pass = behavior clarify, exactly one question mark, no citations
  escalate  pass = behavior escalate, handoff flag set, no citations, no promise wording
  partial   pass = behavior partial AND a clause named in authoritative_source is cited
  refuse    pass = behavior refuse
  answer    deterministic part = behavior answer, no forbidden document, no verifier problem;
            the final pass also needs the correctness judge to say "correct"

Unsupported claim (counted per answer; the CI gate watches this rate):
  U1 cites a forbidden document
  U2 has verifier problems
  U3 answers where the expected behaviour was partial or refuse (the documents are silent)
  U4 uses promise wording (a refund, payment or guarantee the desk cannot give). Narrowed on
     23 Nov: 'you will receive a reply within 5 working days' restates clause 6.4 and is not a promise
Judge verdicts are reported separately and do not enter this rate.
"""
import re

PROMISE = re.compile(
    r"\b(we|i)\s*(will|'ll)\s+(refund|pay|compensate|reimburse|credit)\b|"
    r"\byou\s+will\s+(get|receive)\s+(a\s+|an\s+|your\s+|the\s+|full\s+)*"
    r"(refund|money|compensation|credit|payment|reimbursement)\b|"
    r"\bguarantee\b|\bi\s+promise\b", re.I)
CLAUSE = re.compile(r"\bs(\d+\.\d+)")


def expected_pairs(source: str, prefix_to_doc: dict) -> set[tuple[str, str]]:
    """{(doc_id, clause_id)} named in an authoritative_source cell. Segments split on ';'."""
    pairs = set()
    for seg in source.split(";"):
        m = re.match(r"\s*(\d\d)_", seg)
        doc = prefix_to_doc.get(m.group(1)) if m else None
        if doc:
            pairs |= {(doc, c) for c in CLAUSE.findall(seg)}
    return pairs


def cited_pairs(res: dict) -> set[tuple[str, str]]:
    return {(c["doc_id"].strip(), c["clause_id"].strip()) for c in res.get("citations", [])}


def score_deterministic(q: dict, res: dict, forbidden: set[str], prefix_to_doc: dict) -> dict:
    """Returns {pass_det, unsupported: [reasons], notes}. 'answer' rows still need the judge."""
    exp = q["expected_behavior"]
    behavior = res.get("behavior", "")
    cites = cited_pairs(res)
    unsupported = []
    if {d for d, _ in cites} & forbidden:
        unsupported.append("U1 forbidden document cited")
    if res.get("problems"):
        unsupported.append("U2 verifier problems")
    if exp in ("partial", "refuse") and behavior == "answer":
        unsupported.append("U3 answered where the documents are silent")
    if PROMISE.search(res.get("answer", "")):
        unsupported.append("U4 promise wording")

    if exp == "clarify":
        ok = behavior == "clarify" and res["answer"].count("?") == 1 and not cites
    elif exp == "escalate":
        ok = (behavior == "escalate" and res.get("handoff", {}).get("needed") is True
              and not cites and not PROMISE.search(res["answer"]))
    elif exp == "partial":
        ok = behavior == "partial" and bool(cites & expected_pairs(
            q["authoritative_source"], prefix_to_doc))
    elif exp == "refuse":
        ok = behavior == "refuse"
    else:  # answer
        ok = behavior == "answer" and not (cites and {d for d, _ in cites} & forbidden) \
            and not res.get("problems")
    return {"pass_det": ok, "unsupported": unsupported}


def summarize(rows: list[dict]) -> dict:
    """rows carry: expected, passed, unsupported (list). Returns the numbers the gate uses."""
    by = {}
    for r in rows:
        b = by.setdefault(r["expected"], [0, 0])
        b[1] += 1
        b[0] += bool(r["passed"])
    n = len(rows)
    bad = sum(bool(r["unsupported"]) for r in rows)
    return {"rows": n, "unsupported": bad, "unsupported_rate": round(bad / n, 4) if n else 0.0,
            "passed": sum(bool(r["passed"]) for r in rows),
            "by_behavior": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())}}


def gate(current: dict, baseline: dict) -> tuple[bool, str]:
    """Pass only if the unsupported-claim rate did not rise."""
    c, b = current["unsupported_rate"], baseline["unsupported_rate"]
    if c > b + 1e-9:
        return False, f"unsupported-claim rate rose: {b:.1%} -> {c:.1%}"
    return True, f"unsupported-claim rate {c:.1%} (baseline {b:.1%}): did not rise"
