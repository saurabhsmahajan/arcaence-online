"""Fails when a frozen contract drifts: the clause ids or the answer schema.

Frozen files live in the contracts folder. The latest version of each is the contract.
New clause ids are allowed (new documents arrive) and are only reported; a frozen id that
disappears or is renamed fails. The schema in answer.py must equal the latest frozen file.
No model calls. Run from the rag folder:  uv run python test_contracts.py
"""
import csv
import json
import os
from pathlib import Path

import psycopg
from dotenv import find_dotenv, load_dotenv

from answer import SCHEMA

load_dotenv(find_dotenv(usecwd=True))
CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


def latest(prefix, ext):
    files = sorted(CONTRACTS.glob(f"{prefix}_v*.{ext}"),
                   key=lambda p: int(p.stem.rsplit("_v", 1)[1]))
    if not files:
        raise SystemExit(f"FAIL no frozen {prefix} file in {CONTRACTS}")
    return files[-1]


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


schema_file = latest("answer_schema", "json")
ids_file = latest("clause_ids", "csv")
frozen_schema = json.loads(schema_file.read_text(encoding="utf-8"))
with open(ids_file, newline="", encoding="utf-8") as f:
    frozen_ids = {(r["doc_id"], r["clause_id"]) for r in csv.DictReader(f)}

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    live_ids = set(conn.execute("select doc_id, clause_id from clause_registry").fetchall())

print(f"contract files: {schema_file.name}, {ids_file.name}")
check("the answer schema in answer.py equals the frozen schema", SCHEMA == frozen_schema)
missing = sorted(frozen_ids - live_ids)
check(f"all {len(frozen_ids)} frozen clause ids are still in the registry", not missing)
added = sorted(live_ids - frozen_ids)
print(f"info: {len(added)} clause ids added since the freeze (allowed)")

# The test must be able to fail: break copies and make sure the comparison notices.
drifted = {**SCHEMA, "required": SCHEMA["required"][:-1]}
check("a changed schema would be caught", drifted != frozen_schema)
check("a renamed clause id would be caught", bool(frozen_ids - (live_ids - {next(iter(frozen_ids))})))

print("PASS contracts: clause ids and answer schema match the frozen version")
