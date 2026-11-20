"""Proves search_policy(): same results as the Python query, and the only door in.

Part 1: for every golden-set question, search_policy(k=8) returns exactly the rows the
        original filtered Python query returns (kept as a frozen copy below): same rows,
        same order, same scores.
Part 2: as a logged-in customer the function works and returns only approved clauses;
        direct reads of the knowledge tables are denied; anon cannot call the function.
No model calls. Run from the rag folder:  uv run python test_search_policy.py
"""
import csv
import json
import os
from pathlib import Path

import psycopg
from dotenv import find_dotenv, load_dotenv

from retrieval import embed_query

load_dotenv(find_dotenv(usecwd=True))
GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden_set_core_v1_1.csv"
K = 8


def literal(vec):
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def frozen_reference(conn, question, k):
    """The filtered Python query exactly as it was before search_policy() existed.

    Kept here, not imported, so this test stays a real check after vector_search is
    switched to call the function.
    """
    vec = literal(embed_query(question))
    return conn.execute(
        "select c.doc_id, c.clause_id, d.status, c.content, "
        "1 - (c.embedding <=> %s::vector) as score "
        "from chunks c join documents d on d.doc_id = c.doc_id "
        "where d.status = any(%s) "
        "order by c.embedding <=> %s::vector, d.authority_rank limit %s",
        (vec, ["approved"], vec, k),
    ).fetchall()


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def become(conn, role, sub=None):
    claims = {"role": role}
    if sub:
        claims["sub"] = str(sub)
    conn.execute(f"set local role {role}")
    conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))


def run_as(conn, role, sub, sql, params=()):
    become(conn, role, sub)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.rollback()


def denied(conn, role, sub, sql, params=()):
    become(conn, role, sub)
    try:
        conn.execute(sql, params)
        return False
    except psycopg.errors.InsufficientPrivilege:
        return True
    finally:
        conn.rollback()


with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
    questions = [(r["id"], r["question"]) for r in csv.DictReader(f)]

CALL = "select doc_id, clause_id, status, content, score from search_policy(%s::vector, %s)"

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    # Part 1: the function returns what the Python query returns
    same = 0
    for qid, q in questions:
        old = frozen_reference(conn, q, K)
        new = conn.execute(CALL, (literal(embed_query(q)), K)).fetchall()
        conn.rollback()
        rows_match = [r[:4] for r in old] == [r[:4] for r in new]
        scores_match = all(abs(a[4] - b[4]) < 1e-9 for a, b in zip(old, new))
        if not (rows_match and scores_match):
            check(f"{qid}: function matches the Python query", False)
        same += 1
    check(f"function matches the Python query on all {same} golden questions (k={K})", same == len(questions))

    # Part 2: the door
    cust = conn.execute("select auth_user_id from customers where customer_id = 'cust_001'").fetchone()[0]
    conn.rollback()
    probe = literal(embed_query("How long do I have to request a refund?"))

    rows = run_as(conn, "authenticated", cust, CALL, (probe, K))
    check("a logged-in customer can call search_policy", len(rows) == K)
    check("search_policy returns only approved clauses", {r[2] for r in rows} == {"approved"})

    many = run_as(conn, "authenticated", cust, CALL, (probe, 1000))
    check("match_count is capped at 50", len(many) <= 50)
    check("a huge match_count still returns only approved clauses", {r[2] for r in many} == {"approved"})

    for table in ("chunks", "documents", "clause_registry", "plans_fees"):
        check(f"a logged-in customer cannot read {table} directly",
              denied(conn, "authenticated", cust, f"select * from {table}"))
        check(f"anon cannot read {table} directly",
              denied(conn, "anon", None, f"select * from {table}"))
    check("anon cannot call search_policy",
          denied(conn, "anon", None, CALL, (probe, K)))

print("PASS search_policy: same results as the Python query, and the only door in")
