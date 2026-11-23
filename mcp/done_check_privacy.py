"""Done check for 21 Nov: account deletion never completes in one call.
Starts the real server as ops_writer over stdio and talks to it like an agent would.
It deletes nothing. It opens a deletion request, checks that it stays 'requested', and cancels it again,
so it is safe to run again and again. (Each run adds audit rows and one cancelled request.)
Run from the mcp folder: uv run python done_check_privacy.py"""
import asyncio
import json
import sys

from mcp import StdioServerParameters
from mcp.client import Client

import db_write

fails = 0


def check(label, ok):
    global fails
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        fails += 1


async def call(client, name, args):
    try:
        result = await client.call_tool(name, args)
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)}
    text = "".join(getattr(c, "text", "") for c in result.content)
    if getattr(result, "is_error", False):
        return False, {"error": text}
    try:
        return True, json.loads(text)
    except ValueError:
        return True, {"raw": text}


def db(sql, *params):
    with db_write.connect() as conn:
        return conn.execute(sql, params).fetchall()


def statuses(cust="cust_001"):
    return [r[0] for r in db("select status from ops.deletion_requests where customer_id=%s order by requested_at", cust)]


def counts():
    return db("select (select count(*) from customers), (select count(*) from orders), (select count(*) from invoices)")[0]


async def main():
    params = StdioServerParameters(command=sys.executable, args=["server.py"], env={"OPS_ROLE": "ops_writer"})
    async with Client(params) as client:
        names = sorted(t.name for t in (await client.list_tools()).tools)
        check("no tool exists that approves or completes a deletion", not any("approve" in x or "complete" in x for x in names))

        # leave nothing open from an earlier, interrupted run
        await call(client, "cancel_deletion_request", {"customer_id": "cust_001"})
        before_counts, before_statuses = counts(), statuses()

        ok, data = await call(client, "request_account_deletion", {"customer_id": "cust_001"})
        check("one call opens a request and it is only 'requested'", ok and data.get("status") == "requested" and data.get("kind") == "deletion")
        check("the stored request is 'requested', not completed", statuses()[len(before_statuses):] == ["requested"])
        check("one call deleted nothing: customer, order and invoice counts are unchanged", counts() == before_counts)
        check("the answer tells the agent a person must approve and a waiting period follows",
              "approve" in data.get("next_step", "") and "7-day" in data.get("next_step", ""))

        ok, data = await call(client, "request_account_deletion", {"customer_id": "cust_001"})
        check("a second request is refused, with a reason", ok and data.get("reason") == "request_already_open")

        ok, data = await call(client, "request_account_deletion", {"customer_id": "cust_001", "status": "completed"})
        check("the agent cannot pass a status: an unknown argument is refused", not ok)
        ok, data = await call(client, "request_account_deletion", {"customer_id": "cust_001; drop table customers"})
        check("refused: SQL text in the customer id", not ok)
        ok, data = await call(client, "request_account_deletion", {"customer_id": "cust_999"})
        check("an unknown customer is refused", ok and data.get("reason") == "customer_not_found")

        ok, data = await call(client, "cancel_deletion_request", {"customer_id": "cust_001"})
        check("the open request is cancelled", ok and data.get("status") == "cancelled")
        check("the stored request is 'cancelled', and counts are still unchanged",
              statuses()[len(before_statuses):] == ["cancelled"] and counts() == before_counts)
        ok, data = await call(client, "cancel_deletion_request", {"customer_id": "cust_001"})
        check("cancelling with nothing open is refused", ok and data.get("reason") == "no_open_request")

    rows = db("select outcome, reason from ops.audit_log where tool in ('request_account_deletion','cancel_deletion_request') "
              "order by audit_id desc limit 6")
    check("the refusals are in the audit log", ("refused", "request_already_open") in rows and ("refused", "no_open_request") in rows)
    check("no request anywhere is completed by this run", "completed" not in statuses())


asyncio.run(main())
print("\nALL CHECKS PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
