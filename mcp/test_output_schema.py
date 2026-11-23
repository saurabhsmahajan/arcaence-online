"""Output check: every answer a read tool sends must satisfy the output schema that the tool published.
Found by MCP Inspector on 23 Nov: purchased_at was declared as a date-time while the database column is a date,
so a strict client rejected every get_order answer. This runs the read tools only, so nothing is written.
Run from the mcp folder: uv run python test_output_schema.py"""
import asyncio
import json
import re
import sys

import jsonschema
from mcp import StdioServerParameters
from mcp.client import Client

DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([Zz]|[+-][0-9]{2}:[0-9]{2})")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
formats = jsonschema.FormatChecker()
formats.checks("date-time")(lambda v: not isinstance(v, str) or bool(DATE_TIME.fullmatch(v)))
formats.checks("date")(lambda v: not isinstance(v, str) or bool(DATE.fullmatch(v)))

CASES = [
    ("get_account", {"customer_id": "cust_001"}),
    ("get_account", {"customer_id": "cust_002"}),
    ("get_order", {"order_id": "ord_1001"}),
    ("get_order", {"order_id": "ord_1002"}),
    ("get_order", {"order_id": "ord_2001"}),
    ("get_subscription", {"customer_id": "cust_001"}),
    ("get_subscription", {"customer_id": "cust_002"}),
    ("get_accessibility_info", {}),
]
fails = 0


def check(label, ok):
    global fails
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        fails += 1


async def main():
    params = StdioServerParameters(command=sys.executable, args=["server.py"], env={"OPS_ROLE": "ops_reader"})
    async with Client(params) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        schemas = {n: getattr(t, "output_schema", None) or getattr(t, "outputSchema", None) for n, t in tools.items()}
        check("every read tool publishes an output schema", all(schemas.values()))
        props = schemas["get_order"]["properties"]
        check("get_order publishes purchased_at as a date, as the database stores it", props["purchased_at"].get("format") == "date")
        for name, args in CASES:
            result = await client.call_tool(name, args)
            data = getattr(result, "structured_content", None)
            if data is None:
                data = json.loads("".join(getattr(c, "text", "") for c in result.content))
            try:
                jsonschema.validate(data, schemas[name], format_checker=formats)
                ok = True
            except jsonschema.ValidationError as e:
                print("      ", e.message)
                ok = False
            check(f"{name} {list(args.values())} answers within its published schema", ok)


asyncio.run(main())
print()
print("ALL CHECKS PASS" if fails == 0 else f"{fails} CHECK(S) FAILED")
sys.exit(1 if fails else 0)
