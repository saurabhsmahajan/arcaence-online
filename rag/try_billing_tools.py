"""Live check of the eval adapter against the real databases. No model calls.
It refunds the same order twice, each time in its own case. If the rollback works, the second refund is
allowed too and the cap shows the same remaining amount. Nothing is kept in the database.
Run from the rag folder:  uv run python try_billing_tools.py"""
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from billing_tools import local_tools

load_dotenv(find_dotenv(usecwd=True))
tools = local_tools(Path(__file__).resolve().parent.parent / "mcp")

print("order      :", tools.get_order("ord_1001"))
print("account    :", tools.get_account(customer_id="cust_001"))
hit = tools.search_policy("refund of an unintended renewal within 7 days")["results"][0]
print("policy top :", hit["doc_id"], hit["clause_id"])

remaining = []
for run in (1, 2):
    with tools.case():
        d = tools.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", True, None)
        print(f"run {run} dry    :", d["status"], d.get("reason", ""), d.get("cap_remaining_after", ""))
        c = tools.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", False, d.get("token"))
        print(f"run {run} commit :", c["status"], c.get("reason", ""))
        remaining.append(d.get("cap_remaining_after"))

print("PASS: the second run saw the same cap" if remaining[0] == remaining[1] and remaining[0] else "FAIL: the cap changed between runs")
