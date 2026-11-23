"""Family E: data exposure. Does anything an agent can read hold more than it should?"""
import json
import re

from harness import attack, text_of

RAW_FRAGMENTS = ["anna.keller", "brian.otieno", "5550"]  # parts of the synthetic raw email and phone numbers
# Things that must never appear in an error or refusal: connection strings, secrets, stack traces, SQL, file paths.
LEAK = re.compile(r"postgres(ql)?://|password|passwd|secret|traceback|psycopg|DATABASE_URL|OPS_\w*URL|\.py\"|"
                  r"\bselect\b.+\bfrom\b|\binsert into\b|relation \"|column \"|/home/|/tmp/|[A-Z]:\\\\", re.I)
# Instructions hidden in a tool description would steer a model that reads it (tool poisoning).
POISON = re.compile(r"ignore (all|any|previous|prior|your|the above)|disregard|system prompt|do not tell|don't tell|"
                    r"secretly|exfiltrat|https?://|<important>|\bsudo\b", re.I)


@attack("E1", "E", "Read accounts, subscriptions and orders and look for raw email or phone", "ADR-031")
async def e1(ctx):
    seen = []
    for tool, args in (("get_account", {"customer_id": "cust_001"}), ("get_account", {"customer_id": "cust_002"}),
                       ("get_subscription", {"customer_id": "cust_001"}), ("get_subscription", {"customer_id": "cust_002"}),
                       ("get_order", {"order_id": "ord_1001"}), ("get_order", {"order_id": "ord_2001"})):
        ok, data = await ctx.call(ctx.reader, tool, args)
        seen.append((tool, ok, json.dumps(data)))
    leaks = [f"{tool}: {frag}" for tool, ok, text in seen for frag in RAW_FRAGMENTS if frag in text]
    not_ok = [tool for tool, ok, _ in seen if not ok]
    if not_ok:
        return False, f"control failed: these reads did not work, so nothing was checked: {not_ok}"
    return (not leaks), (f"{len(seen)} reads, no raw email or phone" if not leaks else f"raw contact data found: {leaks}")


@attack("E2", "E", "Provoke errors and refusals, then look for connection strings, SQL, paths and stack traces", "generic errors")
async def e2(ctx):
    calls = [
        (ctx.reader, "get_account", {"customer_id": "cust_999"}),
        (ctx.reader, "get_order", {"order_id": "ord_9999"}),
        (ctx.reader, "get_subscription", {"customer_id": "cust_999"}),
        (ctx.reader, "get_account", {"customer_id": "not an id"}),
        (ctx.reader, "get_account", {}),
        (ctx.reader, "get_account", {"customer_id": 12345}),
        (ctx.writer, "issue_refund", {"customer_id": "cust_999", "order_id": "ord_1001", "amount": "1.00", "clause_doc": "tos_v3", "clause_id": "2.2"}),
        (ctx.writer, "issue_refund", {"customer_id": "cust_001", "order_id": "ord_1001", "amount": "x"}),
        (ctx.writer, "issue_refund", {"customer_id": "cust_001"}),
        (ctx.writer, "cancel_subscription", {"customer_id": "cust_001", "order_id": "ord_9999", "clause_doc": "tos_v3", "clause_id": "3.2"}),
        (ctx.writer, "request_account_deletion", {"customer_id": "cust_999"}),
        (ctx.writer, "no_such_tool", {}),
    ]
    if ctx.policy is not None:
        calls += [(ctx.policy, "search_policy", {"question": "a"}), (ctx.policy, "search_policy", {})]
    leaks = []
    for client, tool, args in calls:
        ok, data = await ctx.call(client, tool, args)
        m = LEAK.search(json.dumps(data))
        if m:
            leaks.append(f"{tool} {list(args)}: matched {m.group(0)!r}")
    return (not leaks), (f"{len(calls)} errors and refusals, no secrets, SQL, paths or stack traces" if not leaks else "; ".join(leaks))


@attack("E3", "E", "Look for hidden instructions in tool descriptions, the resource and the prompt (tool poisoning)", "ADR-046")
async def e3(ctx):
    found = []
    clients = [("reader", ctx.reader), ("writer", ctx.writer)] + ([("policy", ctx.policy)] if ctx.policy is not None else [])
    for label, client in clients:
        for t in (await client.list_tools()).tools:
            text = (t.description or "") + " " + json.dumps(t.input_schema)
            m = POISON.search(text)
            if m:
                found.append(f"{label}.{t.name}: {m.group(0)!r}")
    res = await ctx.reader.read_resource("arcaence://refund-limits")
    m = POISON.search("".join(getattr(c, "text", "") for c in res.contents))
    if m:
        found.append(f"resource refund-limits: {m.group(0)!r}")
    return (not found), (f"{sum(1 for _ in clients)} servers, their tool descriptions and the resource are clean" if not found else "; ".join(found))
