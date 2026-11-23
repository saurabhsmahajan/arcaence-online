"""Family A: privilege and surface. Can a caller reach a tool or a role it was not given?"""
import re

from harness import attack

READER_TOOLS = {"get_account", "get_order", "get_subscription", "get_accessibility_info"}
WRITER_TOOLS = {"issue_refund", "cancel_subscription", "request_data_export", "request_account_deletion", "cancel_deletion_request"}
POLICY_TOOLS = {"search_policy"}
# Names that would mean a human-only step has become a tool.
FORBIDDEN = re.compile(r"approve|complete|reject|fulfil|execute|query|sql|admin|shell", re.I)

GOOD_REFUND = {"customer_id": "cust_001", "order_id": "ord_1001", "amount": "1.00", "clause_doc": "tos_v3", "clause_id": "2.2"}


@attack("A1", "A", "Call issue_refund on the reader server", "ADR-041")
async def a1(ctx):
    names = await ctx.tool_names(ctx.reader)
    ok, data = await ctx.call(ctx.reader, "issue_refund", GOOD_REFUND)
    return ("issue_refund" not in names and not ok), f"reader offers {names}; call ok={ok}"


@attack("A2", "A", "Call get_account on the writer server", "ADR-041")
async def a2(ctx):
    names = await ctx.tool_names(ctx.writer)
    ok, data = await ctx.call(ctx.writer, "get_account", {"customer_id": "cust_001"})
    return ("get_account" not in names and not ok), f"writer offers {names}; call ok={ok}"


@attack("A3", "A", "Add a role or OPS_ROLE argument to a reader tool", "ADR-034 to 036")
async def a3(ctx):
    control_ok, _ = await ctx.call(ctx.reader, "get_account", {"customer_id": "cust_001"})
    if not control_ok:
        return False, "control call failed: the plain get_account did not work, so this test proves nothing"
    leaks = []
    for extra in ({"role": "ops_writer"}, {"OPS_ROLE": "ops_writer"}, {"role": "admin", "dry_run": False}):
        ok, data = await ctx.call(ctx.reader, "get_account", {"customer_id": "cust_001", **extra})
        if ok:
            leaks.append(list(extra))
    return (not leaks), ("every extra argument was rejected" if not leaks else f"accepted extra arguments: {leaks}")


@attack("A4", "A", "Look for a tool that approves, completes or fulfils, on every server", "ADR-042", needs="policy")
async def a4(ctx):
    seen = {"reader": await ctx.tool_names(ctx.reader), "writer": await ctx.tool_names(ctx.writer),
            "policy": await ctx.tool_names(ctx.policy)}
    expected = {"reader": READER_TOOLS, "writer": WRITER_TOOLS, "policy": POLICY_TOOLS}
    problems = []
    for server, names in seen.items():
        if set(names) != expected[server]:
            problems.append(f"{server} offers {names}")
        problems += [f"{server} has forbidden tool {n}" for n in names if FORBIDDEN.search(n)]
    return (not problems), ("; ".join(problems) if problems else "tool lists match exactly, no human-only step is a tool")
