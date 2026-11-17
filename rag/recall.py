import csv
import re
from pathlib import Path

from retrieval import vector_search

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden_set_core.csv"
PREFIX = {"01": "tos_v3", "06": "schedule_ab_v3"}
KMAX = 20
CLAUSE = re.compile(r"(?<![\w.])[sS]?([A-Z]\.\d+|\d+\.\d+)(?![\w.])")


def required(source):
    need = []
    for seg in source.split(";"):
        m = re.match(r"\s*(\d\d)_", seg)
        if not m or m.group(1) not in PREFIX:
            continue
        body = seg.strip().split(" ", 1)[1] if " " in seg.strip() else ""
        need += [f"{PREFIX[m.group(1)]} {c}" for c in CLAUSE.findall(body)]
    return need


def ranks(question, approved):
    order = {}
    for i, r in enumerate(vector_search(question, KMAX, approved_only=approved), 1):
        label = f"{r[0]} {r[1]}" if r[1] else r[0]
        order.setdefault(label, i)
    return order


def fmt(values):
    return " ".join(f"{v:>3}" if v < 99 else ">20" for v in values)


with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
    questions = [r for r in csv.DictReader(f) if r["id"] not in ("Q29", "Q30")]

results = []
print(f"{'id':4} {'trap':4} {'required clauses':34} {'filter on':>14} {'filter off':>14}")
for q in questions:
    need = required(q["authoritative_source"])
    if not need:
        continue
    on, off = ranks(q["question"], True), ranks(q["question"], False)
    rk_on = [on.get(n, 99) for n in need]
    rk_off = [off.get(n, 99) for n in need]
    results.append((max(rk_on), max(rk_off)))
    names = ", ".join(n.split(" ", 1)[1] for n in need)
    print(f"{q['id']:4} {q['trap_id'] or '-':4} {names:34} {fmt(rk_on):>14} {fmt(rk_off):>14}")

print(f"\nQuestions with every required clause inside the top k (of {len(results)}):")
print(f"{'k':>3} {'filter on':>10} {'filter off':>11}")
for k in (3, 4, 5, 8):
    print(f"{k:>3} {sum(a <= k for a, _ in results):>10} {sum(b <= k for _, b in results):>11}")