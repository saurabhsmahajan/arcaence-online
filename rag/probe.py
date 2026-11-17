import csv
import sys
from pathlib import Path

from retrieval import vector_search

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden_set_core.csv"
K = 8


def load(qid):
    with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["id"] == qid:
                return row
    raise SystemExit(f"No question with id {qid}")


def show(title, rows):
    print(f"\n{title}")
    for rank, (doc_id, clause_id, status, content, score) in enumerate(rows, 1):
        label = f"{doc_id} {clause_id}".strip()
        text = " ".join(content.split())[:70]
        print(f"  {rank}. {label:24} {status:11} {float(score):.3f}  {text}")


if __name__ == "__main__":
    qid = sys.argv[1]
    row = load(qid)
    print(f"{qid} | trap {row['trap_id'] or '-'} | expected: {row['expected_behavior']}")
    print(f"Question: {row['question']}")
    print(f"Authoritative source: {row['authoritative_source']}")
    print(f"Must not cite: {row['must_not_cite_files'] or '-'}")
    show("status filter OFF (rag_off)", vector_search(row["question"], K, approved_only=False))
    show("status filter ON  (rag_on)", vector_search(row["question"], K, approved_only=True))