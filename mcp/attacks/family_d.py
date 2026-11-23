"""Family D: irreversible and privacy actions. These attacks must file real requests to have something to attack, so
they are allowed to change the request tables. The harness still fails any attack that approves or completes a
deletion, and each attack cancels the deletion request it opened. (An export request cannot be cancelled by any tool,
so at most one open export request per customer remains until a person fulfils or rejects it.)"""
import json
import re

from harness import attack, audit_count, db_write

VICTIM = "cust_002"
RAW_FRAGMENTS = ["anna.keller", "brian.otieno", "5550"]  # parts of the synthetic raw email and phone numbers


async def clear_open(ctx, customer=VICTIM):
    """Start from a known state: cancel any deletion request left open for this customer."""
    await ctx.call(ctx.writer, "cancel_deletion_request", {"customer_id": customer})


def row_status(request_id) -> str | None:
    with db_write.connect() as conn:
        row = conn.execute("select status from ops.deletion_requests where request_id::text = %s", (str(request_id),)).fetchone()
    return row[0] if row else None


@attack("D1", "D", "Privacy requests for a customer that does not exist", "ADR-042")
async def d1(ctx):
    problems = []
    for tool in ("request_account_deletion", "request_data_export", "cancel_deletion_request"):
        ok, data = await ctx.call(ctx.writer, tool, {"customer_id": "cust_999"})
        if not (ok and data.get("status") == "refused" and data.get("reason") == "customer_not_found"):
            problems.append(f"{tool}: {str(data)[:90]}")
    return (not problems), ("3 tools refused with customer_not_found" if not problems else "; ".join(problems))


@attack("D2", "D", "Two deletion requests in a row for one customer", "ADR-042", may_change=("deletion_requests",))
async def d2(ctx):
    await clear_open(ctx)
    ok1, first = await ctx.call(ctx.writer, "request_account_deletion", {"customer_id": VICTIM})
    before = audit_count("request_account_deletion", "commit", "refused", "request_already_open")
    ok2, second = await ctx.call(ctx.writer, "request_account_deletion", {"customer_id": VICTIM})
    logged = audit_count("request_account_deletion", "commit", "refused", "request_already_open") == before + 1
    await clear_open(ctx)
    good = ok1 and first.get("status") == "requested" and ok2 and second.get("status") == "refused" \
        and second.get("reason") == "request_already_open" and logged
    return good, f"first {first.get('status')}, second {second.get('status')}/{second.get('reason')}, refusal audited: {logged}"


@attack("D3", "D", "Cancel a deletion request when none is open", "ADR-042")
async def d3(ctx):
    await clear_open(ctx)
    ok, data = await ctx.call(ctx.writer, "cancel_deletion_request", {"customer_id": VICTIM})
    return (ok and data.get("status") == "refused" and data.get("reason") == "no_open_request"), f"answer {data.get('status')}/{data.get('reason')}"


@attack("D4", "D", "Smuggle status, reason or dates into the deletion tool", "ADR-042")
async def d4(ctx):
    await clear_open(ctx)
    through = []
    for extra in ({"status": "approved"}, {"status": "completed"}, {"reason": "customer asked by phone"}, {"approved_by": "admin"},
                  {"cooling_off_until": "2020-01-01"}, {"dry_run": False}, {"decided_by": "owner"}):
        ok, data = await ctx.call(ctx.writer, "request_account_deletion", {"customer_id": VICTIM, **extra})
        if ok:
            through.append(f"{list(extra)} -> {str(data)[:70]}")
    await clear_open(ctx)
    return (not through), ("7 extra-argument attempts, all rejected" if not through else f"got through: {through}")


@attack("D5", "D", "A deletion request can only ever be 'requested', never approved or completed", "ADR-042", may_change=("deletion_requests",))
async def d5(ctx):
    await clear_open(ctx)
    ok, data = await ctx.call(ctx.writer, "request_account_deletion", {"customer_id": VICTIM})
    if not (ok and data.get("status") == "requested"):
        return False, f"control failed: the request was not filed ({str(data)[:90]})"
    stored = row_status(data.get("request_id"))
    # Try the other tools that touch this customer to push it further. None can approve or complete.
    for tool, args in (("cancel_subscription", {"customer_id": VICTIM, "order_id": "ord_2001", "clause_doc": "tos_v3", "clause_id": "6.3"}),
                       ("request_account_deletion", {"customer_id": VICTIM})):
        await ctx.call(ctx.writer, tool, args)
    after = row_status(data.get("request_id"))
    await clear_open(ctx)
    return (stored == "requested" and after == "requested"), f"status right after the call: {stored}; after other tools were tried: {after}"


@attack("D6", "D", "The export answer holds counts only, no personal data", "ADR-043", may_change=("export_requests",))
async def d6(ctx):
    ok, data = await ctx.call(ctx.writer, "request_data_export", {"customer_id": "cust_001"})
    text = json.dumps(data)
    leaks = [f for f in RAW_FRAGMENTS if f in text] + (["an email address"] if re.search(r"[\w.]+@[\w.]+", text) else [])
    inventory = data.get("inventory") or {}
    counts_only = all(isinstance(v, int) for v in inventory.values())
    if data.get("status") == "refused" and data.get("reason") == "request_already_open":
        return (not leaks), "a request was already open from an earlier run; its refusal holds no personal data"
    return (ok and not leaks and counts_only and data.get("status") == "requested"), \
        f"status {data.get('status')}, inventory {inventory}, leaks: {leaks or 'none'}"


@attack("D7", "D", "Cancel another customer's open deletion request", "known limit", known_gap=True, may_change=("deletion_requests",))
async def d7(ctx):
    """KNOWN GAP. The server does not know who is calling, so any agent can name any customer id. Today the desk agents
    hold the customer's identity, not the server. The harness records that this is NOT blocked, and that it is audited."""
    await clear_open(ctx)
    ok, filed = await ctx.call(ctx.writer, "request_account_deletion", {"customer_id": VICTIM})
    if not (ok and filed.get("status") == "requested"):
        return False, f"control failed: the victim's request was not filed ({str(filed)[:90]})"
    before = audit_count("cancel_deletion_request", "commit", "allowed", None)
    ok, data = await ctx.call(ctx.writer, "cancel_deletion_request", {"customer_id": VICTIM})
    audited = audit_count("cancel_deletion_request", "commit", "allowed", None) == before + 1
    await clear_open(ctx)
    behaved_as_documented = ok and data.get("status") == "cancelled" and audited
    return behaved_as_documented, f"as documented: the cancel went through for a customer the caller never proved they were ({data.get('status')}), audit row added: {audited}"
