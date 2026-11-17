import csv
import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from retrieval import vector_search

load_dotenv()
GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden_set_core.csv"
PREFIX = {"01": "tos_v3", "06": "schedule_ab_v3"}
CLAUSE = re.compile(r"(?<![\w.])[sS]?([A-Z]\.\d+|\d+\.\d+)(?![\w.])")
XREF = re.compile(r"Section (\d+\.\d+)")


def required(source):
    need = []
    for seg in source.split(";"):
        m = re.match(r"\s*(\d\d)_", seg)
        if not m or m.group(1) not in PREFIX:
            continue
        body = seg.strip().split(" ", 1)[1] if " " in seg.strip() else ""
        need += [f"{PREFIX[m.group(1)]} {c}" for c in CLAUSE.findall(body)]
    return need


def label(r):
    return f"{r[0]} {r[1]}" if r[1] else r[0]


def load_chunks():
    sql = ("select c.doc_id, c.clause_id, c.content from chunks c "
           "join documents d on d.doc_id = c.doc_id "
           "where d.status = 'approved' and c.clause_id is not null")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return {f"{d} {c}": text for d, c, text in conn.execute(sql).fetchall()}


def expand(base, chunks, crossref, neighbours):
    out = dict.fromkeys(base)
    for lab in base:
        doc, _, clause = lab.partition(" ")
        if not clause:
            continue
        if crossref:
            for ref in XREF.findall(chunks.get(lab, "")):
                if f"{doc} {ref}" in chunks:
                    out.setdefault(f"{doc} {ref}")
        if neighbours:
            pre, _, num = clause.rpartition(".")
            if num.isdigit():
                for n in (int(num) - 1, int(num) + 1):
                    if f"{doc} {pre}.{n}" in chunks:
                        out.setdefault(f"{doc} {pre}.{n}")
    return list(out)


chunks = load_chunks()
print(f"approved clause chunks loaded: {len(chunks)}")
with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
    questions = [r for r in csv.DictReader(f) if r["id"] not in ("Q29", "Q30")]

variants = {
    "k=8 (today)": lambda b8, b12: b8,
    "k=12": lambda b8, b12: b12,
    "k=8 + cross-reference": lambda b8, b12: expand(b8, chunks, True, False),
    "k=8 + neighbours": lambda b8, b12: expand(b8, chunks, False, True),
    "k=8 + both": lambda b8, b12: expand(b8, chunks, True, True),
}
covered = {name: set() for name in variants}
sizes = {name: [] for name in variants}
total = 0
for q in questions:
    need = required(q["authoritative_source"])
    if not need:
        continue
    total += 1
    b8 = [label(r) for r in vector_search(q["question"], 8, approved_only=True)]
    b12 = [label(r) for r in vector_search(q["question"], 12, approved_only=True)]
    for name, fn in variants.items():
        got = fn(b8, b12)
        sizes[name].append(len(got))
        if all(n in got for n in need):
            covered[name].add(q["id"])

print(f"\n{'strategy':24} {'covered':>8} {'avg chunks':>11} {'max chunks':>11}")
for name in variants:
    s = sizes[name]
    print(f"{name:24} {len(covered[name]):>5}/{total} {sum(s) / len(s):>11.1f} {max(s):>11}")

base = covered["k=8 (today)"]
print("\nQuestions each strategy newly covers compared with k=8:")
for name in list(variants)[1:]:
    print(f"  {name:24} {sorted(covered[name] - base) or '-'}")