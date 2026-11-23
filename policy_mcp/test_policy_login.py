"""The policy_reader login against the real database: it can run search_policy() and nothing else.
Read-only. Run from the policy_mcp folder: uv run python test_policy_login.py"""
import os
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values, load_dotenv

import config

load_dotenv()
POLICY = os.environ["OPS_POLICY_DATABASE_URL"]
OWNER = os.environ.get("DATABASE_URL") or dotenv_values(Path(__file__).resolve().parent.parent / "rag" / ".env").get("DATABASE_URL")
if not OWNER:
    sys.exit("Owner DATABASE_URL not found in the environment or rag/.env")

VEC = "[" + ",".join(f"{0.01 * ((i % 7) + 1):.6f}" for i in range(config.EMBED_DIMENSIONS)) + "]"
SEARCH = "select doc_id, clause_id from public.search_policy(%s::vector, 8)"
n = 0


def check(label, ok):
    global n
    n += 1
    assert ok, f"FAILED: {label}"
    print(f"PASS  {label}")


def refused(sql, params=None):
    with psycopg.connect(POLICY) as conn:
        try:
            conn.execute(sql, params)
        except psycopg.Error:
            conn.rollback()
            return True
        conn.rollback()
        return False


with psycopg.connect(POLICY) as conn:
    check("the login is policy_reader", conn.execute("select current_user").fetchone()[0] == config.ROLE)
    mine = conn.execute(SEARCH, (VEC,)).fetchall()
    check("it can call search_policy and gets passages back", len(mine) > 0)
    check("its sessions are read-only", conn.execute("show default_transaction_read_only").fetchone()[0] == "on")

with psycopg.connect(OWNER) as conn:
    theirs = conn.execute(SEARCH, (VEC,)).fetchall()
    statuses = {r[0] for r in conn.execute("select d.status from documents d where d.doc_id = any(%s)", ([r[0] for r in mine],)).fetchall()}
check("it sees exactly the rows the owner sees through the same function", mine == theirs)
check("every document it can see is approved", statuses == {"approved"})

check("it cannot read the chunks table", refused("select count(*) from chunks"))
check("it cannot read the documents table", refused("select count(*) from documents"))
check("it cannot read customer data", refused("select count(*) from customers"))
check("it cannot read the ops schema", refused("select count(*) from ops.audit_log"))
check("it cannot call the accessibility function", refused("select * from public.accessibility_statement()"))
check("it cannot write", refused("create table public.should_not_exist (x int)"))
print(f"\nALL {n} CHECKS PASS")
