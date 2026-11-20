"""Write the frozen contract files: the clause ids and the answer schema.

Run from the rag folder:  uv run python scripts\\freeze_contracts.py
A version is written once. It refuses to overwrite one that exists; a deliberate change
is a new version (--version 2) plus an ADR, never an edit of an old file.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import find_dotenv, load_dotenv

RAG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAG))
from answer import SCHEMA  # noqa: E402

load_dotenv(find_dotenv(usecwd=True))
CONTRACTS = RAG.parent / "contracts"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, default=1)
    args = ap.parse_args()

    ids_path = CONTRACTS / f"clause_ids_v{args.version}.csv"
    schema_path = CONTRACTS / f"answer_schema_v{args.version}.json"
    if ids_path.exists() or schema_path.exists():
        raise SystemExit(f"v{args.version} already exists and is frozen; nothing written. "
                         "A change is a new version (--version N) with an ADR.")

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        pairs = conn.execute(
            "select doc_id, clause_id from clause_registry order by doc_id, clause_id"
        ).fetchall()

    CONTRACTS.mkdir(exist_ok=True)
    with open(ids_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "clause_id"])
        w.writerows(pairs)
    schema_path.write_text(json.dumps(SCHEMA, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    print(f"Wrote {ids_path.name} ({len(pairs)} clause ids) and {schema_path.name}")


if __name__ == "__main__":
    main()
