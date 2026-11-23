"""The accessibility read tool and the one database function behind it (migration 012).
Read-only. The one check that changes a document's status does it inside a transaction that is rolled back.
Run from the mcp folder: uv run python test_accessibility.py"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values, load_dotenv

import server

load_dotenv()
READER = os.environ["OPS_DATABASE_URL"]
OWNER = os.environ.get("DATABASE_URL") or dotenv_values(Path(__file__).resolve().parent.parent / "rag" / ".env").get("DATABASE_URL")
if not OWNER:
    sys.exit("Owner DATABASE_URL not found in the environment or rag/.env")

n = 0


def check(label, ok):
    global n
    n += 1
    assert ok, f"FAILED: {label}"
    print(f"PASS  {label}")


info = server.get_accessibility_info()
check("the tool returns the approved clause, cited as tos_v3 6.4", info.citation == "tos_v3 6.4")
check("the wording names the WCAG 2.1 level AA standard", "WCAG 2.1" in info.statement and "AA" in info.statement)
check("the wording gives the reply time of 5 working days", "5 working days" in info.statement)
check("the wording does not mention a screen reader mode (Q39 trap)", "screen reader" not in info.statement.lower())
check("the note tells the agent not to promise features the wording omits", "must not be promised" in info.note)

with psycopg.connect(READER) as conn:
    rows = conn.execute("select doc_id, clause_id from public.accessibility_statement()").fetchall()
    check("the database function returns exactly one row, tos_v3 6.4", rows == [("tos_v3", "6.4")])
    try:
        conn.execute("select count(*) from chunks")
        direct = True
    except psycopg.Error:
        direct = False
    check("the reader login still cannot read the knowledge tables directly", not direct)
    conn.rollback()
    try:
        conn.execute("select * from public.search_policy(array_fill(0, array[384])::vector, 1)")
        door = True
    except psycopg.Error:
        door = False
    check("and it cannot call search_policy: that stays for the second server", not door)

with psycopg.connect(OWNER) as conn:
    conn.execute("update documents set status = 'superseded' where doc_id = 'tos_v3'")
    rows = conn.execute("select * from public.accessibility_statement()").fetchall()
    check("if tos_v3 stops being approved, the function returns nothing", rows == [])
    conn.rollback()

print(f"\nALL {n} CHECKS PASS")
