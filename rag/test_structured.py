from answer import check

given = {"tos_v3 2.3", "tos_v3 2.1", "schedule_ab_v3 B.1"}

def result(*cites):
    return {"answer": "Refunds get a reply within 5 working days.",
            "citations": [{"doc_id": d, "clause_id": c} for d, c in cites],
            "refused": False, "refusal_reason": ""}

valid = result(("tos_v3", "2.3"))
made_up = result(("tos_v9", "7.7"))
not_given = result(("tos_v3", "9.9"))
no_cites = result()

for name, r in [("valid", valid), ("made-up", made_up), ("not given", not_given), ("no cites", no_cites)]:
    print(f"{name:10}", check(r, given))

assert check(valid, given) == [], "valid citation was rejected"
assert check(made_up, given), "made-up citation was NOT rejected"
assert check(not_given, given), "citation not in the given sources was NOT rejected"
assert check(no_cites, given), "uncited answer was NOT rejected"
assert not any("no citation" in p for p in check(made_up, given)), "rejected for the wrong reason"
print("PASS")