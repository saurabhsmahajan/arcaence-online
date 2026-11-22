"""AOP ops MCP server. The role fixed at launch (OPS_ROLE) decides which tools exist:
ops_reader gets the three read tools, ops_writer gets issue_refund and cancel_subscription.
Run: uv run python server.py"""
from typing import Annotated

from pydantic import Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import actions
import audit
import config
import db
import db_write
import policy
from masking import mask_email, mask_phone
from models import Account, CustomerId, Order, OrderId, Subscription, SubscriptionOrder, WriteResult

mcp = MCPServer("arcaence-ops")


@mcp.tool(description="Look up one customer's account: plan, billing, currency, status.")
def get_account(customer_id: CustomerId) -> Account:
    row = db.fetch_account(customer_id)
    if row is None:
        raise ToolError(f"No account found for {customer_id}")
    email, phone = row.pop("email"), row.pop("phone")
    return Account(**row, email_masked=mask_email(email), phone_masked=mask_phone(phone))


@mcp.tool(description="Look up one order, with its invoice if one was issued.")
def get_order(order_id: OrderId) -> Order:
    row = db.fetch_order(order_id)
    if row is None:
        raise ToolError(f"No order found for {order_id}")
    return Order(**row)


@mcp.tool(description="Look up a customer's subscription: plan, billing, status and subscription orders.")
def get_subscription(customer_id: CustomerId) -> Subscription:
    acct = db.fetch_account(customer_id)
    if acct is None:
        raise ToolError(f"No account found for {customer_id}")
    orders = [SubscriptionOrder(**r) for r in db.fetch_subscription_orders(customer_id)]
    return Subscription(
        customer_id=acct["customer_id"],
        plan=acct["plan"],
        billing=acct["billing"],
        currency=acct["currency"],
        status=acct["status"],
        subscription_orders=orders,
    )


# --- write tools (registered here, kept only when the launch role is ops_writer) ---

Amount = Annotated[str, Field(max_length=20, description="Amount as text with at most 2 decimals, e.g. '19.00'")]
ClauseDoc = Annotated[str | None, Field(max_length=40, description="Document the clause is in, e.g. tos_v3")]
ClauseId = Annotated[str | None, Field(max_length=40, description="Clause number, e.g. 2.2")]
Token = Annotated[str | None, Field(max_length=100, description="The token returned by the dry run")]


def _result(raw: dict) -> WriteResult:
    raw = dict(raw)
    for key in ("refund", "cancellation"):
        if key in raw:
            raw["preview"] = raw.pop(key)
    return WriteResult(**raw)


def _run(tool: str, mode: str, fields: dict, work) -> WriteResult:
    """Run one write in one transaction. Any failure rolls it back and is reported without internal detail."""
    try:
        with db_write.connect() as conn:
            return _result(work(conn))
    except Exception:  # noqa: BLE001 - nothing internal is shown to the caller
        try:
            audit.log_standalone(tool=tool, mode=mode, outcome="error", reason="internal_error", **fields)
        except Exception:  # noqa: BLE001 - the audit also failed: still fail closed
            pass
        raise ToolError("The action could not be completed and was not applied.") from None


@mcp.tool(description=(
    "Refund part of one order. Call first with dry_run=true (the default): it checks the rules and returns a "
    "preview and a single-use token, and refunds nothing. To go ahead, call again with dry_run=false, the same "
    "arguments and that token. A clause from the terms is required. Refusals return a reason code."))
def issue_refund(customer_id: CustomerId, order_id: OrderId, amount: Amount,
                 clause_doc: ClauseDoc = None, clause_id: ClauseId = None,
                 dry_run: bool = True, confirm_token: Token = None) -> WriteResult:
    req = policy.RefundRequest(customer_id, order_id, amount, clause_doc, clause_id)
    fields = {"customer_id": customer_id, "order_id": order_id}
    if dry_run:
        return _run("issue_refund", "dry_run", fields, lambda c: actions.dry_run_refund(c, req))
    return _run("issue_refund", "commit", fields, lambda c: actions.commit_refund(c, req, confirm_token))


@mcp.tool(description=(
    "Cancel one subscription order. Call first with dry_run=true (the default): it checks the rules and returns "
    "a preview and a single-use token, and cancels nothing. To go ahead, call again with dry_run=false, the same "
    "arguments and that token. A clause from the terms is required. Refusals return a reason code."))
def cancel_subscription(customer_id: CustomerId, order_id: OrderId,
                        clause_doc: ClauseDoc = None, clause_id: ClauseId = None,
                        dry_run: bool = True, confirm_token: Token = None) -> WriteResult:
    req = policy.CancelRequest(customer_id, order_id, clause_doc, clause_id)
    fields = {"customer_id": customer_id, "order_id": order_id}
    if dry_run:
        return _run("cancel_subscription", "dry_run", fields, lambda c: actions.dry_run_cancel(c, req))
    return _run("cancel_subscription", "commit", fields, lambda c: actions.commit_cancel(c, req, confirm_token))


def lock_down() -> None:
    """Startup hardening: keep only this role's tools, and reject unknown arguments."""
    for tool in list(mcp._tool_manager.list_tools()):
        if tool.name not in config.ALLOWED_TOOLS:
            mcp.remove_tool(tool.name)
            continue
        arg_model = tool.fn_metadata.arg_model
        arg_model.model_config["extra"] = "forbid"
        arg_model.model_rebuild(force=True)
        tool.parameters = arg_model.model_json_schema()


lock_down()

if __name__ == "__main__":
    (db_write if config.ROLE == "ops_writer" else db).assert_login_role(config.ROLE)
    mcp.run(transport="stdio")
