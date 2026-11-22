"""Call the three tools through the db layer against the real database (no MCP client yet)."""
import json
import server

for label, fn, arg in [
    ("get_account cust_001", server.get_account, "cust_001"),
    ("get_order ord_1001", server.get_order, "ord_1001"),
    ("get_subscription cust_002", server.get_subscription, "cust_002"),
]:
    print("==", label)
    print(json.dumps(fn(arg).model_dump(mode="json"), indent=2))
