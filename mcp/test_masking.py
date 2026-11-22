"""Run: uv run python test_masking.py"""
import asyncio
import datetime as dt

import db
import server
from masking import mask_email, mask_phone

RAW_EMAIL, RAW_PHONE = "anna.keller@example.com", "+00 5550 1001"

assert mask_email(RAW_EMAIL) == "a***@example.com"
assert mask_email("not-an-email") == "***"
assert mask_email(None) is None
assert mask_phone(RAW_PHONE) == "+** **** **01"
assert mask_phone("12") == "***"
assert mask_phone(None) is None
print("PASS  masking functions")

db.fetch_account = lambda c: {
    "customer_id": c, "display_name": "Customer One (synthetic)", "plan": "Pro", "billing": "monthly",
    "currency": "EUR", "status": "active", "created_at": dt.datetime(2026, 1, 5),
    "email": RAW_EMAIL, "phone": RAW_PHONE,
}


async def check():
    result = await server.mcp.call_tool("get_account", {"customer_id": "cust_001"})
    text = str(result)
    assert RAW_EMAIL not in text and "anna.keller" not in text, "raw email leaked"
    assert RAW_PHONE not in text and "5550" not in text, "raw phone leaked"
    assert "a***@example.com" in text and "+** **** **01" in text
    print("PASS  get_account output contains masked values only")


asyncio.run(check())
