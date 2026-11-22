"""Done check for 19 Nov: read tools return masked data, and the role cannot be changed by an argument.
Starts the real server over stdio and talks to it like an agent would.
Run: uv run python done_check.py"""
import asyncio
import json
import sys

from mcp import StdioServerParameters
from mcp.client import Client

RAW_FRAGMENTS = ["anna.keller", "brian.otieno", "5550"]  # parts of the synthetic raw email/phone


def text_of(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def call(client, name, args):
    """Return (ok, text). A refused call counts as not ok, whether it raises or flags an error."""
    try:
        result = await client.call_tool(name, args)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    return (not getattr(result, "is_error", False)), text_of(result)


async def run(client) -> int:
    failures = 0

    def check(label, passed):
        nonlocal failures
        print(("PASS  " if passed else "FAIL  ") + label)
        failures += 0 if passed else 1

    tools = (await client.list_tools()).tools
    names = sorted(t.name for t in tools)
    check(f"server offers exactly the three read tools {names}",
          names == ["get_account", "get_order", "get_subscription"])
    check("no tool declares a role argument", all("role" not in t.input_schema["properties"] for t in tools))

    for cid in ("cust_001", "cust_002"):
        ok, text = await call(client, "get_account", {"customer_id": cid})
        data = json.loads(text) if ok else {}
        check(f"get_account {cid} returns masked contact data",
              ok and "***" in data.get("email_masked", "") and not any(f in text for f in RAW_FRAGMENTS))

    ok, text = await call(client, "get_order", {"order_id": "ord_1001"})
    check("get_order ord_1001 returns the order with its invoice", ok and "inv_1001" in text)

    ok, text = await call(client, "get_subscription", {"customer_id": "cust_002"})
    check("get_subscription cust_002 returns the subscription", ok and "Team" in text)

    for label, args in [
        ("role=admin added to a call", {"customer_id": "cust_001", "role": "admin"}),
        ("role=ops_writer added to a call", {"customer_id": "cust_001", "role": "ops_writer"}),
        ("SQL text in the id", {"customer_id": "cust_001' or '1'='1"}),
    ]:
        ok, _ = await call(client, "get_account", args)
        check(f"refused: {label}", not ok)

    ok, _ = await call(client, "update_account", {"customer_id": "cust_001", "plan": "Team"})
    check("refused: calling a write tool that does not exist", not ok)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else str(failures) + ' CHECK(S) FAILED'}")
    return failures


async def main() -> int:
    params = StdioServerParameters(command="uv", args=["run", "python", "server.py"])
    async with Client(params) as client:
        return await run(client)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
