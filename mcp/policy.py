"""Policy checks for the write tools. Pure functions: facts in, a reason code or None out. No database here."""
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import config

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


@lru_cache(maxsize=1)
def clause_registry() -> frozenset[tuple[str, str]]:
    """The latest frozen list of real (doc_id, clause_id) pairs. Missing file means the check fails closed."""
    files = sorted(CONTRACTS.glob("clause_ids_v*.csv"), key=lambda p: int(p.stem.rsplit("_v", 1)[1]))
    if not files:
        raise RuntimeError("no frozen clause contract found in contracts/")
    with files[-1].open(encoding="utf-8-sig", newline="") as f:
        return frozenset((r["doc_id"], r["clause_id"]) for r in csv.DictReader(f))


@dataclass(frozen=True)
class RefundRequest:
    customer_id: str
    order_id: str
    amount: object  # whatever the caller sent; parsed here
    clause_doc: str | None
    clause_id: str | None


@dataclass(frozen=True)
class RefundFacts:
    order: dict | None            # the order row, or None if it does not exist
    refunded_on_order: Decimal    # already refunded on this order
    refunded_by_customer: Decimal # already refunded to this customer, in the order's currency


def parse_amount(value) -> Decimal | None:
    """A positive money amount with at most two decimals, else None."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        return None
    return amount


def check_clause(doc: str | None, clause: str | None, allowed: frozenset) -> str | None:
    if not doc or not clause:
        return "no_clause"
    if (doc, clause) not in clause_registry():
        return "unknown_clause"
    if (doc, clause) not in allowed:
        return "clause_not_allowed"
    return None


def check_refund(req: RefundRequest, facts: RefundFacts) -> str | None:
    """Return the reason code for the first failed check, or None if the refund may go ahead."""
    amount = parse_amount(req.amount)
    if amount is None:
        return "invalid_amount"
    reason = check_clause(req.clause_doc, req.clause_id, config.REFUND_CLAUSES)
    if reason:
        return reason
    order = facts.order
    if order is None:
        return "order_not_found"
    if order["customer_id"] != req.customer_id:
        return "wrong_customer"
    if amount > order["amount"] - facts.refunded_on_order:
        return "over_refundable"
    cap = config.REFUND_CAP.get(order["currency"])
    if cap is None or facts.refunded_by_customer + amount > cap:
        return "over_cap"
    return None


@dataclass(frozen=True)
class CancelRequest:
    customer_id: str
    order_id: str
    clause_doc: str | None
    clause_id: str | None


@dataclass(frozen=True)
class CancelFacts:
    order: dict | None  # order_id, customer_id, kind
    already_cancelled: bool


def check_cancel(req: CancelRequest, facts: CancelFacts) -> str | None:
    """Return the reason code for the first failed check, or None if the cancellation may go ahead."""
    reason = check_clause(req.clause_doc, req.clause_id, config.CANCEL_CLAUSES)
    if reason:
        return reason
    order = facts.order
    if order is None:
        return "order_not_found"
    if order["customer_id"] != req.customer_id:
        return "wrong_customer"
    if order["kind"] != "subscription" or facts.already_cancelled:
        return "subscription_not_active"
    return None
