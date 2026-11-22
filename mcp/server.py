"""AOP ops MCP server: three read-only tools. Run: uv run python server.py"""
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

import config
import db
from masking import mask_email, mask_phone
from models import Account, CustomerId, Order, OrderId, Subscription, SubscriptionOrder

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
    db.assert_login_role(config.ROLE)
    mcp.run(transport="stdio")
