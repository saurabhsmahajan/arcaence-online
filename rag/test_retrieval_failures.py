from retrieval import vector_search

K = 8
Q28 = "I read that I have 14 days to get a refund on a one-off purchase. Is that right?"


def label(row):
    doc_id, clause_id = row[0], row[1]
    return f"{doc_id} {clause_id}" if clause_id else doc_id


# FL-001 stale version: three near-identical versions of clause 2.2 compete
on = vector_search(Q28, K, approved_only=True)
off = vector_search(Q28, K, approved_only=False)
off_order = [label(r) for r in off]
spread = [float(r[4]) for r in off if label(r) in ("tos_v2 2.2", "tos_v3 2.2", "draft_v3_5 2.2")]

print("filter on :", [label(r) for r in on][:3], "...")
print("filter off:", off_order[:3], "...")
print(f"score spread across the three clause 2.2 versions: {max(spread) - min(spread):.3f}")

assert {r[2] for r in on} == {"approved"}, "filter on returned non-approved text"
assert label(on[0]) == "tos_v3 2.2", "filter on: v3 clause 2.2 is not first"
assert {r[2] for r in off} - {"approved"}, "filter off no longer returns stale text"
assert off_order.index("tos_v2 2.2") < off_order.index("tos_v3 2.2"), "planted failure gone: v2 no longer outranks v3"
assert max(spread) - min(spread) < 0.01, "versions are no longer near-identical"
print("PASS FL-001: fix holds and the planted failure is still reproducible")

# FL-002 rule split across clauses: the formula clause 3.5 ranks low, but 3.6 points to it
import csv
from pathlib import Path

from retrieval import expand_references

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden_set_core.csv"


def question(qid):
    with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
        return next(r["question"] for r in csv.DictReader(f) if r["id"] == qid)


NEEDED = {"Q07": ["tos_v3 3.5", "tos_v3 3.6"], "Q38": ["tos_v3 3.4", "tos_v3 3.5", "tos_v3 3.6"]}
for qid, need in NEEDED.items():
    base = vector_search(question(qid), K, approved_only=True)
    expanded = expand_references(base, approved_only=True)
    base_labels = {label(r) for r in base}
    exp_labels = {label(r) for r in expanded}
    print(f"{qid}: top-8 has {[n for n in need if n in base_labels]}; after expansion +{len(expanded) - len(base)} chunk(s)")
    assert all(n in exp_labels for n in need), f"{qid}: a required clause is still missing"
    assert len(expanded) - len(base) <= 2, f"{qid}: expansion added too many chunks"
    assert {r[2] for r in expanded} == {"approved"}, f"{qid}: expansion added non-approved text"

q07_base = {label(r) for r in vector_search(question("Q07"), K, approved_only=True)}
assert "tos_v3 3.5" not in q07_base, "planted failure gone: Q07 now finds 3.5 without expansion"
print("PASS FL-002: pointer expansion recovers 3.5 and adds at most 2 chunks")

# FL-003 law versus policy: both sides must be retrieved together; similarity does not rank law first
LAW = ["consumer_act 2.2", "consumer_act 3.1", "consumer_act 3.2"]
q29 = question("Q29")
on = vector_search(q29, K, approved_only=True)
on_labels = [label(r) for r in on]
off_labels = [label(r) for r in vector_search(q29, K, approved_only=False)]
print("Q29 filter on :", on_labels)
print("Q29 filter off:", off_labels)

assert "tos_v3 2.2" in on_labels, "policy clause 2.2 missing from the top 8"
assert all(item in on_labels for item in LAW), "a conflicting statute clause is missing from the top 8"
assert {r[2] for r in on if r[0] == "consumer_act"} == {"approved"}, "statute rows are not approved"
first_law = min(on_labels.index(item) for item in LAW)
assert on_labels.index("tos_v3 2.2") < first_law, "characterization changed: law now outranks policy by similarity alone"
assert not all(item in off_labels for item in LAW), "filter off now returns the whole statute side"
print("PASS FL-003 (retrieval half): policy and statute retrieved together; law is not ranked first by similarity")