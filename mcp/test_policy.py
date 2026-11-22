"""Policy checks, on the synthetic seed data. No database needed. Run: uv run python test_policy.py"""
from decimal import Decimal as D

import config
import policy
from policy import RefundFacts, RefundRequest

ORD_1001 = {"order_id": "ord_1001", "customer_id": "cust_001", "amount": D("19.00"), "currency": "EUR"}
ORD_1002 = {"order_id": "ord_1002", "customer_id": "cust_001", "amount": D("49.00"), "currency": "EUR"}
ORD_2001 = {"order_id": "ord_2001", "customer_id": "cust_002", "amount": D("540.00"), "currency": "USD"}
GOOD = ("tos_v3", "2.2")


def req(order="ord_1001", cust="cust_001", amount="19.00", clause=GOOD):
    doc, cid = clause if clause else (None, None)
    return RefundRequest(cust, order, amount, doc, cid)


def facts(order=ORD_1001, on_order="0", by_customer="0"):
    return RefundFacts(order, D(on_order), D(by_customer))


n = 0


def check(label, got, want):
    global n
    n += 1
    assert got == want, f"{label}: got {got!r}, wanted {want!r}"
    print(f"PASS  {label}")


check("a valid refund within every limit is allowed", policy.check_refund(req(), facts()), None)

check("no clause at all is refused", policy.check_refund(req(clause=None), facts()), "no_clause")
check("a clause document without a clause id is refused", policy.check_refund(req(clause=("tos_v3", "")), facts()), "no_clause")
check("an invented clause is refused", policy.check_refund(req(clause=("tos_v3", "9.9")), facts()), "unknown_clause")
check("a superseded clause is refused even though its id exists",
      policy.check_refund(req(clause=("tos_v2", "2.2")), facts()), "clause_not_allowed")
draft = sorted(c for c in policy.clause_registry() if c[0] == "draft_v3_5")[0]
check("a draft clause is refused even though its id exists", policy.check_refund(req(clause=draft), facts()), "clause_not_allowed")
check("a real approved clause that is not a refund basis is refused",
      policy.check_refund(req(clause=("tos_v3", "5.3")), facts()), "clause_not_allowed")

for bad in ("0", "-5", "abc", "19.001", "NaN", "Infinity", None):
    check(f"amount {bad!r} is refused", policy.check_refund(req(amount=bad), facts()), "invalid_amount")

check("an unknown order is refused", policy.check_refund(req(order="ord_9999"), facts(order=None)), "order_not_found")
check("another customer's order is refused", policy.check_refund(req(cust="cust_002"), facts()), "wrong_customer")
check("refunding more than the order is refused", policy.check_refund(req(amount="20.00"), facts()), "over_refundable")
check("refunding more than what is left on the order is refused",
      policy.check_refund(req(amount="10.00"), facts(on_order="10.00")), "over_refundable")

check("a refund over the cap is refused (540 USD against a 55 USD cap)",
      policy.check_refund(req(order="ord_2001", cust="cust_002", amount="540.00"), facts(order=ORD_2001)), "over_cap")
check("the cap counts what the customer already received (19 + 49 EUR against 50)",
      policy.check_refund(req(order="ord_1002", amount="49.00"), facts(order=ORD_1002, by_customer="19.00")), "over_cap")
check("many small refunds cannot get past the cap (45 received, 6 more asked)",
      policy.check_refund(req(amount="6.00"), facts(by_customer="45.00")), "over_cap")
check("exactly the cap is allowed (45 received, 5 more asked)",
      policy.check_refund(req(amount="5.00"), facts(by_customer="45.00")), None)

check("a currency with no cap is refused", policy.check_refund(
    req(), facts(order={**ORD_1001, "currency": "GBP"})), "over_cap")

for name, allowed in (("refund", config.REFUND_CLAUSES), ("cancel", config.CANCEL_CLAUSES)):
    check(f"every {name} clause on the list exists in the frozen registry", allowed <= policy.clause_registry(), True)

print(f"\n{n} checks passed")
