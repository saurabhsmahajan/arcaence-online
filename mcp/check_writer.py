"""Smoke test for the write database and its login.
Every allowed write is rolled back, so this leaves nothing behind.
Run from the mcp folder: uv run python check_writer.py"""
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
WRITER = os.environ["OPS_WRITER_DATABASE_URL"]
READER = os.environ["OPS_DATABASE_URL"]


def attempt(label, url, sql, expect_ok):
    # a fresh connection each time; an allowed statement is rolled back so nothing is kept
    try:
        with psycopg.connect(url) as conn:
            conn.execute(sql)
            conn.rollback()
        outcome, detail = "ok", ""
    except Exception as e:  # noqa: BLE001
        outcome, detail = "refused", type(e).__name__
    verdict = "PASS" if (outcome == "ok") == expect_ok else "FAIL"
    print(f"{verdict}  {label}: {outcome} {detail}")


# reads the writer needs
attempt("writer reads customer columns without contact data", WRITER,
        "select customer_id, plan, billing, currency, status from customers", True)
attempt("writer reads orders", WRITER, "select order_id, amount from orders", True)
attempt("writer cannot read the email column", WRITER, "select email from customers", False)
attempt("writer cannot read the phone column", WRITER, "select phone from customers", False)

# writes the writer is allowed
attempt("writer can add an audit row", WRITER,
        "insert into ops.audit_log (server_role, tool, mode, outcome) values ('check', 'check_writer', 'dry_run', 'allowed')", True)
attempt("writer can add a token row", WRITER,
        "insert into ops.confirm_tokens (token_hash, tool, args_hash, expires_at) values ('x', 't', 'a', now())", True)
attempt("writer can mark a token used", WRITER,
        "update ops.confirm_tokens set used_at = now() where token_hash = 'x'", True)

# writes the writer must not have
attempt("writer cannot change an audit row", WRITER, "update ops.audit_log set reason = 'x'", False)
attempt("writer cannot delete an audit row", WRITER, "delete from ops.audit_log", False)
attempt("writer cannot truncate the audit log", WRITER, "truncate ops.audit_log", False)
attempt("writer cannot rewrite a token's arguments", WRITER, "update ops.confirm_tokens set args_hash = 'b'", False)
attempt("writer cannot change a refund after it is made", WRITER, "update ops.refunds set amount = 1", False)
attempt("writer cannot write to the customer tables", WRITER,
        "insert into customers (customer_id, display_name) values ('cust_999', 'x')", False)
attempt("writer cannot touch the RAG tables", WRITER, "select * from clause_registry", False)

# the read-only login must still be boxed in, and must not see the new schema
attempt("ops_reader cannot read the write database", READER, "select * from ops.refunds", False)
attempt("ops_reader cannot read the audit log", READER, "select * from ops.audit_log", False)
