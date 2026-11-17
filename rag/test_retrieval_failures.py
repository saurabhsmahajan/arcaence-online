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