"""Family C: money abuse. Every attack here uses dry runs and refused commits only, so no refund is ever made and the
customer's cap is never used up. (Many small refunds and expired tokens are proven below the transport, in
test_policy.py and test_actions.py, because proving them over the wire would need a real commit.)"""
from harness import attack, audit_count, db_write

REFUND = {"customer_id": "cust_001", "order_id": "ord_1001", "amount": "19.00", "clause_doc": "tos_v3", "clause_id": "2.2"}
CANCEL = {"customer_id": "cust_001", "order_id": "ord_1001", "clause_doc": "tos_v3", "clause_id": "3.2"}


def refused(data, reason):
    return data.get("status") == "refused" and data.get("reason") == reason


def used_tokens() -> int:
    with db_write.connect() as conn:
        return conn.execute("select count(*) from ops.confirm_tokens where used_at is not null").fetchone()[0]


async def check_refusals(ctx, tool, cases):
    """cases: list of (label, arguments, expected reason). Returns the list of problems."""
    problems = []
    for label, args, reason in cases:
        ok, data = await ctx.call(ctx.writer, tool, args)
        if not (ok and refused(data, reason)):
            problems.append(f"{label}: expected {reason}, got ok={ok} {str(data)[:90]}")
    return problems


def verdict(problems, n, what):
    return (not problems), (f"{n} {what}, all refused with the expected reason" if not problems else "; ".join(problems))


@attack("C1", "C", "Refund of 540 USD against a 55 USD cap, in a dry run", "ADR-038")
async def c1(ctx):
    before = audit_count("issue_refund", "dry_run", "refused", "over_cap")
    ok, data = await ctx.call(ctx.writer, "issue_refund", {**REFUND, "customer_id": "cust_002", "order_id": "ord_2001", "amount": "540.00"})
    logged = audit_count("issue_refund", "dry_run", "refused", "over_cap") == before + 1
    return (ok and refused(data, "over_cap") and logged), f"answer {data.get('status')}/{data.get('reason')}, audit row added: {logged}"


@attack("C2", "C", "Refund more than the order's remaining refundable amount", "ADR-038")
async def c2(ctx):
    problems = await check_refusals(ctx, "issue_refund", [
        ("19.01 on a 19.00 order", {**REFUND, "amount": "19.01"}, "over_refundable"),
        ("50.00 on a 19.00 order", {**REFUND, "amount": "50.00"}, "over_refundable"),
    ])
    return verdict(problems, 2, "oversized refunds")


@attack("C3", "C", "Refund with no clause, a document only, or an id only", "ADR-039")
async def c3(ctx):
    base = {k: v for k, v in REFUND.items() if not k.startswith("clause")}
    before = audit_count("issue_refund", "dry_run", "refused", "no_clause")
    problems = await check_refusals(ctx, "issue_refund", [
        ("no clause fields", base, "no_clause"),
        ("document without id", {**base, "clause_doc": "tos_v3"}, "no_clause"),
        ("id without document", {**base, "clause_id": "2.2"}, "no_clause"),
    ])
    logged = audit_count("issue_refund", "dry_run", "refused", "no_clause") == before + 3
    if not logged:
        problems.append("the three refusals were not all in the audit log")
    return verdict(problems, 3, "clause-less refunds")


@attack("C4", "C", "Invented, superseded, draft and wrong-purpose clauses", "ADR-039")
async def c4(ctx):
    problems = await check_refusals(ctx, "issue_refund", [
        ("invented clause", {**REFUND, "clause_id": "9.9"}, "unknown_clause"),
        ("superseded document", {**REFUND, "clause_doc": "tos_v2"}, "clause_not_allowed"),
        ("draft document", {**REFUND, "clause_doc": "draft_v3_5"}, "clause_not_allowed"),
        ("real approved clause that is not a refund basis", {**REFUND, "clause_id": "6.3"}, "clause_not_allowed"),
    ])
    return verdict(problems, 4, "bad clauses")


@attack("C5", "C", "Commit with no token and with a made-up token", "ADR-037")
async def c5(ctx):
    before = audit_count("issue_refund", "commit", "refused", "token_missing")
    problems = await check_refusals(ctx, "issue_refund", [
        ("no token", {**REFUND, "dry_run": False}, "token_missing"),
        ("made-up token", {**REFUND, "dry_run": False, "confirm_token": "not-a-real-token"}, "token_invalid"),
        ("token of the right length, wrong value", {**REFUND, "dry_run": False, "confirm_token": "A" * 43}, "token_invalid"),
    ])
    if audit_count("issue_refund", "commit", "refused", "token_missing") != before + 1:
        problems.append("the missing-token refusal was not audited")
    return verdict(problems, 3, "token-less commits")


@attack("C6", "C", "A real token used for a different amount, order or customer", "ADR-037")
async def c6(ctx):
    ok, preview = await ctx.call(ctx.writer, "issue_refund", REFUND)
    token = preview.get("token", "")
    if not (ok and preview.get("status") == "preview" and token):
        return False, f"control failed: a normal dry run gave no token ({str(preview)[:90]})"
    used_before = used_tokens()
    problems = await check_refusals(ctx, "issue_refund", [
        ("different amount", {**REFUND, "amount": "18.00", "dry_run": False, "confirm_token": token}, "args_mismatch"),
        ("different order", {**REFUND, "order_id": "ord_1002", "amount": "19.00", "dry_run": False, "confirm_token": token}, "args_mismatch"),
        ("different clause", {**REFUND, "clause_id": "3.3", "dry_run": False, "confirm_token": token}, "args_mismatch"),
    ])
    if used_tokens() != used_before:
        problems.append("a mismatched commit spent the token")
    return verdict(problems, 3, "mismatched commits")


@attack("C7", "C", "Use a refund token to cancel a subscription", "ADR-037")
async def c7(ctx):
    ok, preview = await ctx.call(ctx.writer, "issue_refund", REFUND)
    token = preview.get("token", "")
    if not (ok and token):
        return False, f"control failed: a normal dry run gave no token ({str(preview)[:90]})"
    ok, data = await ctx.call(ctx.writer, "cancel_subscription", {**CANCEL, "dry_run": False, "confirm_token": token})
    return (ok and data.get("status") == "refused" and data.get("reason") in ("token_invalid", "args_mismatch")), \
        f"answer {data.get('status')}/{data.get('reason')}"


@attack("C8", "C", "Refund another customer's order, and an order that does not exist", "ADR-039")
async def c8(ctx):
    problems = await check_refusals(ctx, "issue_refund", [
        ("cust_002 on cust_001's order", {**REFUND, "customer_id": "cust_002"}, "wrong_customer"),
        ("cust_001 on cust_002's order", {**REFUND, "order_id": "ord_2001"}, "wrong_customer"),
        ("an order that does not exist", {**REFUND, "order_id": "ord_9999"}, "order_not_found"),
    ])
    return verdict(problems, 3, "ownership attacks")


@attack("C9", "C", "Cancel a one-off purchase, and cancel with a refund-only clause", "ADR-039")
async def c9(ctx):
    problems = await check_refusals(ctx, "cancel_subscription", [
        ("a one-off order is not a subscription", {**CANCEL, "order_id": "ord_1002"}, "subscription_not_active"),
        ("another customer's subscription", {**CANCEL, "customer_id": "cust_002"}, "wrong_customer"),
        ("a refund clause used to cancel", {**CANCEL, "clause_id": "2.2"}, "clause_not_allowed"),
    ])
    return verdict(problems, 3, "cancellation attacks")
