"""Done check, part 2: the role is fixed at launch and no argument can change it.
Run: uv run python test_role.py"""
import asyncio
import datetime as dt
import os
import subprocess
import sys

import config
import db
import server

db.fetch_account = lambda c: {
    "customer_id": c, "display_name": "Customer One (synthetic)", "plan": "Pro", "billing": "monthly",
    "currency": "EUR", "status": "active", "created_at": dt.datetime(2026, 1, 5),
    "email": "anna.keller@example.com", "phone": "+00 5550 1001",
} if c == "cust_001" else None


async def main():
    tools = await server.mcp.list_tools()
    names = sorted(t.name for t in tools)
    assert names == sorted(config.ALLOWED_TOOLS), names
    print("PASS  tool list is exactly the role's tools:", names)

    for t in tools:
        props = t.input_schema["properties"]
        assert "role" not in props, t.name
        assert t.input_schema.get("additionalProperties") is False, t.name
    print("PASS  no tool has a role argument, and every schema forbids extra arguments")

    for bad in ({"role": "admin"}, {"OPS_ROLE": "writer"}, {"customer_id": "cust_001", "role": "admin"}):
        try:
            await server.mcp.call_tool("get_account", {"customer_id": "cust_001", **bad} if "customer_id" not in bad else bad)
            raise AssertionError(f"accepted {bad}")
        except AssertionError:
            raise
        except Exception as e:  # noqa: BLE001
            assert "role" in str(e).lower() or "extra" in str(e).lower() or "OPS_ROLE" in str(e), str(e)
    print("PASS  calls with a role argument (or any unknown argument) are refused")

    ok = await server.mcp.call_tool("get_account", {"customer_id": "cust_001"})
    assert "cust_001" in str(ok)
    print("PASS  a normal call still works")


asyncio.run(main())

env = {**os.environ, "OPS_ROLE": "admin"}
r = subprocess.run([sys.executable, "-c", "import config"], env=env, capture_output=True, text=True)
assert r.returncode != 0 and "Unknown OPS_ROLE" in r.stderr, r.stderr
print("PASS  an unknown OPS_ROLE at launch stops the server")
