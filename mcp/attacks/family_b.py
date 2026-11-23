"""Family B: injection and malformed input. Does anything hostile get past the input checks?"""
import time

from harness import attack

CLAUSE = {"clause_doc": "tos_v3", "clause_id": "2.2"}


def id_targets(ctx, bad_customer=None, bad_order=None):
    """Every (client, tool, arguments) that takes an id, with the hostile value put into the id field."""
    out = []
    if bad_customer is not None:
        out += [
            (ctx.reader, "get_account", {"customer_id": bad_customer}),
            (ctx.reader, "get_subscription", {"customer_id": bad_customer}),
            (ctx.writer, "request_data_export", {"customer_id": bad_customer}),
            (ctx.writer, "request_account_deletion", {"customer_id": bad_customer}),
            (ctx.writer, "cancel_deletion_request", {"customer_id": bad_customer}),
            (ctx.writer, "issue_refund", {"customer_id": bad_customer, "order_id": "ord_1001", "amount": "1.00", **CLAUSE}),
            (ctx.writer, "cancel_subscription", {"customer_id": bad_customer, "order_id": "ord_1001", "clause_doc": "tos_v3", "clause_id": "6.3"}),
        ]
    if bad_order is not None:
        out += [
            (ctx.reader, "get_order", {"order_id": bad_order}),
            (ctx.writer, "issue_refund", {"customer_id": "cust_001", "order_id": bad_order, "amount": "1.00", **CLAUSE}),
            (ctx.writer, "cancel_subscription", {"customer_id": "cust_001", "order_id": bad_order, "clause_doc": "tos_v3", "clause_id": "6.3"}),
        ]
    return out


async def try_all(ctx, targets):
    """Send each target. A target is blocked only if the call was rejected. Returns the list that got through."""
    through = []
    for client, tool, args in targets:
        ok, data = await ctx.call(client, tool, args)
        if ok:
            through.append(f"{tool} {str(list(args.values()))[:60]} -> {str(data)[:80]}")
    return through


def verdict(through, total, what):
    return (not through), (f"{total} calls with {what}, all rejected" if not through else f"{len(through)} of {total} got through: {through[:3]}")


@attack("B1", "B", "SQL text in an id field, on every tool that takes an id", "exact-pattern ids")
async def b1(ctx):
    sql_c = "cust_001'; DROP TABLE ops.refunds;--"
    sql_o = "ord_1001' OR '1'='1"
    targets = id_targets(ctx, sql_c, sql_o)
    through = await try_all(ctx, targets)
    from harness import db_write
    with db_write.connect() as conn:
        table_ok = conn.execute("select to_regclass('ops.refunds') is not null").fetchone()[0]
    ok, detail = verdict(through, len(targets), "SQL text")
    return ok and table_ok, detail + ("" if table_ok else "; ops.refunds is GONE")


@attack("B2", "B", "Wildcards and path text in ids", "exact-pattern ids")
async def b2(ctx):
    through, total = [], 0
    for bad in ("cust_%", "cust_*", "cust_00_", "cust_001/../cust_002", "cust_001 OR 1=1", "../../etc/passwd", "cust_001,cust_002"):
        t = id_targets(ctx, bad_customer=bad)
        total += len(t)
        through += await try_all(ctx, t)
    for bad in ("ord_*", "ord_%", "ord_100_", "ord_1001;ord_1002"):
        t = id_targets(ctx, bad_order=bad)
        total += len(t)
        through += await try_all(ctx, t)
    return verdict(through, total, "wildcards and path text")


@attack("B3", "B", "A 10,000-character id", "length limits")
async def b3(ctx):
    start = time.monotonic()
    targets = id_targets(ctx, "cust_" + "9" * 10000, "ord_" + "9" * 10000)
    through = await try_all(ctx, targets)
    took = time.monotonic() - start
    ok, detail = verdict(through, len(targets), "10,000-character ids")
    return ok and took < 10, f"{detail} in {took:.1f}s"


@attack("B4", "B", "Non-ASCII digits and a trailing newline in an id", "exact-pattern ids")
async def b4(ctx):
    arabic = "cust_٠٠١"        # Arabic-Indic digits
    fullwidth = "cust_００１"      # full-width digits
    newline = "cust_001\n"
    o_arabic = "ord_١٠٠١"
    through, total = [], 0
    for bad in (arabic, fullwidth, newline):
        t = id_targets(ctx, bad_customer=bad)
        total += len(t)
        through += await try_all(ctx, t)
    t = id_targets(ctx, bad_order=o_arabic)
    total += len(t)
    through += await try_all(ctx, t)
    return verdict(through, total, "non-ASCII digits or a newline")


@attack("B5", "B", "Odd amounts: exponent, negative, zero, too many decimals, NaN, comma, spaces", "ADR-038")
async def b5(ctx):
    amounts = ["1e2", "-5", "0", "0.00", "10.999", "NaN", "Infinity", "10,5", " 19.00", "19.00\n", "0x10", "１９.00", "1_0.00", "+19.00", "19.", ".5"]
    through = []
    for amt in amounts:
        ok, data = await ctx.call(ctx.writer, "issue_refund",
                                  {"customer_id": "cust_001", "order_id": "ord_1001", "amount": amt, **CLAUSE})
        # blocked = rejected by the schema, or refused by policy. A preview or token means it got through.
        if ok and data.get("status") != "refused":
            through.append(f"{amt!r} -> {str(data)[:80]}")
    return verdict(through, len(amounts), "odd amounts")
