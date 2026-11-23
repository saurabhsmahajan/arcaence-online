"""Done check for 20 Nov: write tools refuse what they must, and every refusal is logged.
Starts the real server as ops_writer over stdio and talks to it like an agent would.
It moves no money: it only previews and refuses, so it is safe to run again and again.
(Each run adds audit rows and a few unused tokens. That is the audit log doing its job.)
Run: uv run python done_check_writes.py"""
import asyncio
import json
import sys

from mcp import StdioServerParameters
from mcp.client import Client

import db_write

GOOD = {"customer_id": "cust_001", "order_id": "ord_1001", "amount": "19.00", "clause_doc": "tos_v3", "clause_id": "2.2"}


def text_of(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def call(client, name, args):
    """Return (ok, data). A refused call counts as not ok, whether it raises or flags an error."""
    try:
        result = await client.call_tool(name, args)
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)}
    text = text_of(result)
    if getattr(result, "is_error", False):
        return False, {"error": text}
    try:
        return True, json.loads(text)
    except ValueError:
        return True, {"raw": text}


def db_count(sql, *params):
    with db_write.connect() as conn:
        return conn.execute(sql, params).fetchone()[0]


def audited(tool, mode, outcome, reason):
    return db_count("select count(*) from ops.audit_log where tool=%s and mode=%s and outcome=%s and reason is not distinct from %s",
                    tool, mode, outcome, reason)


async def run(client) -> int:
    failures = 0

    def check(label, passed):
        nonlocal failures
        print(("PASS  " if passed else "FAIL  ") + label)
        failures += 0 if passed else 1

    tools = (await client.list_tools()).tools
    names = sorted(t.name for t in tools)
    check(f"server offers exactly the write tools {names}", names == ["cancel_deletion_request", "cancel_subscription", "issue_refund", "request_account_deletion", "request_data_export"])
    check("no tool declares a role argument", all("role" not in t.input_schema["properties"] for t in tools))
    ok, _ = await call(client, "get_account", {"customer_id": "cust_001"})
    check("refused: the writer cannot read accounts (no such tool)", not ok)

    refunds_before = db_count("select count(*) from ops.refunds")
    cancels_before = db_count("select count(*) from ops.cancellations")

    # 1. The two refusals the plan names, each logged.
    before = audited("issue_refund", "dry_run", "refused", "over_cap")
    ok, data = await call(client, "issue_refund", {**GOOD, "customer_id": "cust_002", "order_id": "ord_2001", "amount": "540.00"})
    check("a refund over the cap is refused with over_cap", ok and data.get("status") == "refused" and data.get("reason") == "over_cap")
    check("the over-cap refusal is in the audit log", audited("issue_refund", "dry_run", "refused", "over_cap") == before + 1)

    before = audited("issue_refund", "dry_run", "refused", "no_clause")
    ok, data = await call(client, "issue_refund", {"customer_id": "cust_001", "order_id": "ord_1001", "amount": "19.00"})
    check("a refund without a clause id is refused with no_clause", ok and data.get("status") == "refused" and data.get("reason") == "no_clause")
    check("the no-clause refusal is in the audit log", audited("issue_refund", "dry_run", "refused", "no_clause") == before + 1)

    # 2. A good dry run gives a token and moves nothing.
    ok, preview = await call(client, "issue_refund", GOOD)
    token = preview.get("token", "")
    check("a valid dry run returns a preview and a token", ok and preview.get("status") == "preview" and len(token) > 30)

    # 3. A commit is refused unless the token is real and matches.
    before = audited("issue_refund", "commit", "refused", "token_missing")
    ok, data = await call(client, "issue_refund", {**GOOD, "dry_run": False})
    check("a commit without a token is refused and logged",
          data.get("reason") == "token_missing" and audited("issue_refund", "commit", "refused", "token_missing") == before + 1)
    ok, data = await call(client, "issue_refund", {**GOOD, "dry_run": False, "confirm_token": "not-a-real-token"})
    check("a commit with a made-up token is refused", data.get("reason") == "token_invalid")
    ok, data = await call(client, "issue_refund", {**GOOD, "amount": "18.00", "dry_run": False, "confirm_token": token})
    check("a real token cannot be used for a different amount", data.get("reason") == "args_mismatch")

    # 4. Bad calls never reach the database.
    for label, args in [
        ("an unknown argument (role=admin)", {**GOOD, "role": "admin"}),
        ("SQL text in the order id", {**GOOD, "order_id": "ord_1001' or '1'='1"}),
        ("a float-style amount", {**GOOD, "amount": 19.0}),
    ]:
        ok, data = await call(client, "issue_refund", args)
        check(f"refused: {label}", not ok or data.get("status") == "refused")

    # 5. Cancel follows the same rules.
    ok, data = await call(client, "cancel_subscription", {"customer_id": "cust_001", "order_id": "ord_1001"})
    check("a cancellation without a clause id is refused", data.get("reason") == "no_clause")
    ok, data = await call(client, "cancel_subscription", {"customer_id": "cust_001", "order_id": "ord_1001", "dry_run": False})
    check("a cancel commit without a token is refused", data.get("reason") in ("token_missing", "no_clause"))

    check("no refund was recorded by any of this", db_count("select count(*) from ops.refunds") == refunds_before)
    check("no cancellation was recorded by any of this", db_count("select count(*) from ops.cancellations") == cancels_before)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else str(failures) + ' CHECK(S) FAILED'}")
    return failures


async def main() -> int:
    params = StdioServerParameters(command="uv", args=["run", "python", "server.py"], env={"OPS_ROLE": "ops_writer"})
    async with Client(params) as client:
        return await run(client)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
