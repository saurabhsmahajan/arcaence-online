"""Offline checks for the policy server: no model, no database. Run from the policy_mcp folder:
uv run python test_policy_server.py"""
import asyncio
import os
import subprocess
import sys

import config
import db
import embed
import server

n = 0


def check(label, ok):
    global n
    n += 1
    assert ok, f"FAILED: {label}"
    print(f"PASS  {label}")


calls = []
ROWS = [
    {"doc_id": "tos_v3", "clause_id": "2.2", "content": "2.2 A refund may be requested within 7 days.", "score": 0.83219},
    {"doc_id": "email_x", "clause_id": None, "content": "A note with no clause number.", "score": 0.5},
]
embed.embed_query = lambda q: [0.1] * config.EMBED_DIMENSIONS
db.search = lambda vec, k: (calls.append((len(vec), k)) or ROWS)


async def refused(args):
    try:
        await server.mcp.call_tool("search_policy", args)
    except Exception:  # noqa: BLE001
        return True
    return False


async def main():
    tools = await server.mcp.list_tools()
    check("the server offers exactly one tool, search_policy", [t.name for t in tools] == ["search_policy"])
    props = tools[0].input_schema["properties"]
    check("the schema allows only question and k, and forbids extra arguments",
          set(props) == {"question", "k"} and tools[0].input_schema.get("additionalProperties") is False)
    check("k is bounded by the schema", props["k"].get("maximum") == config.MAX_K and props["k"].get("minimum") == 1)

    res = await server.mcp.call_tool("search_policy", {"question": "How long do I have to ask for a refund?"})
    text = str(res)
    check("a normal call returns the passages with their citations", "tos_v3 2.2" in text and "within 7 days" in text)
    check("a passage with no clause number is cited by its document only", "email_x" in text)
    check("the question was turned into 384 numbers and the default of 5 passages asked for", calls[-1] == (384, config.DEFAULT_K))
    check("the result tells the agent the passages are not instructions", "Not instructions" in text)

    await server.mcp.call_tool("search_policy", {"question": "refund window", "k": 3})
    check("k is passed through", calls[-1][1] == 3)

    check("k = 0 is refused", await refused({"question": "refund window", "k": 0}))
    check("k above the limit is refused", await refused({"question": "refund window", "k": config.MAX_K + 1}))
    check("a question that is too short is refused", await refused({"question": "hi"}))
    check("a question that is too long is refused", await refused({"question": "x" * (config.MAX_QUESTION + 1)}))
    check("an unknown argument is refused", await refused({"question": "refund window", "doc_id": "tos_v2"}))
    check("an attempt to turn off the status filter is refused", await refused({"question": "refund window", "approved_only": False}))

    def boom(vec, k):
        raise RuntimeError("connection string postgresql://user:SECRET@host/db")

    db.search = boom
    try:
        await server.mcp.call_tool("search_policy", {"question": "refund window"})
        leaked = None
    except Exception as e:  # noqa: BLE001
        leaked = str(e)
    check("a database failure gives a generic message with no internal detail",
          leaked is not None and "unavailable" in leaked and "SECRET" not in leaked and "postgresql" not in leaked)


asyncio.run(main())

check("the login role is a constant, not read from the environment", config.ROLE == "policy_reader")
r = subprocess.run([sys.executable, "-c", "import config; print(config.ROLE)"],
                   env={**os.environ, "OPS_ROLE": "ops_writer", "ROLE": "ops_writer"}, capture_output=True, text=True)
check("no environment variable can change it", r.stdout.strip() == "policy_reader")
print(f"\nALL {n} CHECKS PASS")
