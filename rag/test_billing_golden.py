"""Checks the billing golden set against the world it describes. No model, no database, no keys.

A label that disagrees with the seed data or the cap would make the eval measure the wrong thing, so
every settled and queued row is checked against the orders and the caps before any model runs.
"""
import csv
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from billing_logic import AMOUNT, CUSTOMER_ID, LABEL, ORDER_ID, OUTCOMES, QUEUE_REASONS

PATH = Path(__file__).resolve().parent.parent / "eval" / "golden_set_billing.csv"
COLUMNS = ["id", "message", "customer_id", "as_of", "expected_outcome", "expected_reasons", "expected_amount",
           "expected_order_id", "expected_clause", "category", "split", "notes"]

# Migration 004 (synthetic data) and mcp/config.py. Copied here only to check the labels, never used by the agent.
ORDERS = {
    "ord_1001": {"customer": "cust_001", "amount": Decimal("19.00"), "currency": "EUR", "purchased": date(2026, 11, 1), "downloaded": False},
    "ord_1002": {"customer": "cust_001", "amount": Decimal("49.00"), "currency": "EUR", "purchased": date(2026, 10, 31), "downloaded": True},
    "ord_2001": {"customer": "cust_002", "amount": Decimal("540.00"), "currency": "USD", "purchased": date(2026, 9, 15), "downloaded": False},
}
CAP = {"EUR": Decimal("50.00"), "USD": Decimal("55.00"), "INR": Decimal("4500.00")}
CLAUSE = re.compile(r"[a-z0-9_]{1,40} [0-9.]{1,10}")

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


with PATH.open(encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    check(reader.fieldnames == COLUMNS, "columns are exactly as written in the rules")
    rows = list(reader)

check(len(rows) == 14, "14 rows")
check(len({r["id"] for r in rows}) == 14, "ids are unique")
check(all(re.fullmatch(r"B[0-9]{2}", r["id"]) for r in rows), "ids look like B01")
check(sum(r["split"] == "dev" for r in rows) == 10 and sum(r["split"] == "holdout" for r in rows) == 4, "10 dev and 4 holdout")
check({r["split"] for r in rows} == {"dev", "holdout"}, "only two splits")
check({r["expected_outcome"] for r in rows} == set(OUTCOMES), "every outcome has a row")
check(len({r["message"] for r in rows}) == 14, "no message is repeated")

for r in rows:
    i = r["id"]
    check(CUSTOMER_ID.fullmatch(r["customer_id"]) is not None, f"{i}: customer id is valid")
    check(r["message"] and len(r["message"]) <= 500, f"{i}: message is present and short")
    check(r["message"] == r["message"].strip(), f"{i}: no stray space around the message")
    as_of = date.fromisoformat(r["as_of"])
    out = r["expected_outcome"]
    check(out in OUTCOMES, f"{i}: outcome is known")
    reasons = [x for x in r["expected_reasons"].split("|") if x]
    check(all(LABEL.fullmatch(x) for x in reasons), f"{i}: reasons are lowercase codes")
    check(r["category"] and r["notes"], f"{i}: category and notes are filled in")

    if out == "settled":
        check(reasons == [], f"{i}: a settled row has no reason")
        check(AMOUNT.fullmatch(r["expected_amount"]) and ORDER_ID.fullmatch(r["expected_order_id"]), f"{i}: settled row names an amount and an order")
        check(CLAUSE.fullmatch(r["expected_clause"]) is not None, f"{i}: settled row names a clause")
        o = ORDERS[r["expected_order_id"]]
        amount = Decimal(r["expected_amount"])
        check(o["customer"] == r["customer_id"], f"{i}: the order belongs to the customer")
        check(Decimal("0") < amount <= o["amount"], f"{i}: the amount is positive and not over the order")
        check(amount <= CAP[o["currency"]], f"{i}: the amount is within the cap")
        check(0 <= (as_of - o["purchased"]).days <= 7, f"{i}: inside the 7 days of the clause")
        check(not o["downloaded"], f"{i}: the order was not downloaded")
        check(r["expected_order_id"] in r["message"] and r["expected_amount"] in r["message"], f"{i}: the message states the order and amount")
    else:
        check(r["expected_amount"] == "" and r["expected_order_id"] == "" and r["expected_clause"] == "", f"{i}: only a settled row has an amount, order and clause")
        check(len(reasons) >= 1, f"{i}: a row that is not settled has a reason")

    if out == "queued":
        check(set(reasons) == set(QUEUE_REASONS), f"{i}: queued means over_cap")
        oid = re.search(r"ord_[0-9]{4}", r["message"]).group(0)
        o = ORDERS[oid]
        amount = Decimal(re.search(r"([0-9]+\.[0-9]{2}) (EUR|USD|INR)", r["message"]).group(1))
        check(o["customer"] == r["customer_id"], f"{i}: the order belongs to the customer")
        check(CAP[o["currency"]] < amount <= o["amount"], f"{i}: over the cap and not over the order")
        check(0 <= (as_of - o["purchased"]).days <= 7 and not o["downloaded"], f"{i}: the clause would fit, so only the cap stops it")

    if out == "refused" and "not_eligible" in reasons and r["category"] == "condition_not_met":
        o = ORDERS[re.search(r"ord_[0-9]{4}", r["message"]).group(0)]
        check(o["downloaded"], f"{i}: the condition that is not met is real")
    if r["category"] == "window_passed":
        o = ORDERS[re.search(r"ord_[0-9]{4}", r["message"]).group(0)]
        check((as_of - o["purchased"]).days > 7, f"{i}: the window really has passed")
    if r["category"] == "other_customers_order":
        o = ORDERS[re.search(r"ord_[0-9]{4}", r["message"]).group(0)]
        check(o["customer"] != r["customer_id"], f"{i}: the order is someone else's")
    if r["category"] == "unknown_order":
        check(re.search(r"ord_[0-9]{4}", r["message"]).group(0) not in ORDERS, f"{i}: the order does not exist")
    if r["category"] == "over_order_amount":
        o = ORDERS[re.search(r"ord_[0-9]{4}", r["message"]).group(0)]
        check(Decimal(re.search(r"([0-9]+\.[0-9]{2}) (EUR|USD)", r["message"]).group(1)) > o["amount"], f"{i}: the amount really is over the order")

cats = {r["category"] for r in rows}
for needed in ("injection", "injection_with_real_request", "condition_not_met", "unverifiable_claim", "over_cap",
               "settled_in_window", "partial_amount", "not_a_refund", "missing_details"):
    check(needed in cats, f"a row for {needed}")
check(sum(r["expected_outcome"] == "settled" for r in rows) >= 3 and sum(r["expected_outcome"] == "queued" for r in rows) >= 1, "money rows exist")

print(f"BILLING GOLDEN SET CHECKS: {n} checks passed")
