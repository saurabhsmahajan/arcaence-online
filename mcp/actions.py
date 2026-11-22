"""The refund action: a dry run that returns a single-use token, then a commit that spends it.

The caller owns the connection and the commit:

    with db_write.connect() as conn:
        result = actions.commit_refund(conn, request, token)

Inside, every write happens in a savepoint together with its audit row, so a refund without its audit
record is impossible. A refusal rolls the savepoint back and then records the refusal."""
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from decimal import Decimal

import audit
import config
import policy
from policy import CancelFacts, CancelRequest, RefundFacts, RefundRequest

TOOL = "issue_refund"
CANCEL_TOOL = "cancel_subscription"
CENT = Decimal("0.01")

_DOC = re.compile(r"^[a-z0-9_]{1,40}$")
_CLAUSE = re.compile(r"^\d{1,2}\.\d{1,2}$")
_CUSTOMER = re.compile(r"^cust_\d{3}$")
_ORDER = re.compile(r"^ord_\d{4}$")


class _Refusal(Exception):
    def __init__(self, reason: str):
        self.reason = reason


@contextmanager
def _savepoint(conn, name: str):
    # `name` is always a fixed word from this file, never caller input.
    conn.execute(f"savepoint {name}")
    try:
        yield
    except BaseException:
        conn.execute(f"rollback to savepoint {name}")
        conn.execute(f"release savepoint {name}")
        raise
    else:
        conn.execute(f"release savepoint {name}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value, pattern):
    """Only a value of the expected shape may reach the audit log. Anything else is left out."""
    return value if isinstance(value, str) and pattern.match(value) else None


def _amount(req: RefundRequest) -> Decimal | None:
    amount = policy.parse_amount(req.amount)
    return None if amount is None else amount.quantize(CENT)


def _hash_args(fields: dict) -> str:
    return _sha(json.dumps(fields, sort_keys=True))


def _args_hash(req: RefundRequest, amount: Decimal) -> str:
    return _hash_args(
        {"tool": TOOL, "customer_id": req.customer_id, "order_id": req.order_id,
         "amount": format(amount, "f"), "clause_doc": req.clause_doc, "clause_id": req.clause_id}
    )


def _cancel_hash(req: CancelRequest) -> str:
    return _hash_args(
        {"tool": CANCEL_TOOL, "customer_id": req.customer_id, "order_id": req.order_id,
         "clause_doc": req.clause_doc, "clause_id": req.clause_id}
    )


def _facts(conn, req: RefundRequest) -> RefundFacts:
    row = conn.execute(
        "select order_id, customer_id, amount, currency from orders where order_id = %s", (req.order_id,)
    ).fetchone()
    if row is None:
        return RefundFacts(None, Decimal(0), Decimal(0))
    order = {"order_id": row[0], "customer_id": row[1], "amount": row[2], "currency": row[3]}
    on_order = conn.execute(
        "select coalesce(sum(amount), 0) from ops.refunds where order_id = %s", (req.order_id,)
    ).fetchone()[0]
    by_customer = conn.execute(
        "select coalesce(sum(amount), 0) from ops.refunds where customer_id = %s and currency = %s",
        (req.customer_id, order["currency"]),
    ).fetchone()[0]
    return RefundFacts(order, Decimal(on_order), Decimal(by_customer))


def _audit_fields(req, amount, facts, mode, outcome, reason=None):
    doc, cid = _clean(req.clause_doc, _DOC), _clean(req.clause_id, _CLAUSE)
    args = {
        "customer_id": _clean(req.customer_id, _CUSTOMER),
        "order_id": _clean(req.order_id, _ORDER),
        "amount": None if amount is None else format(amount, "f"),
        "clause_doc": doc,
        "clause_id": cid,
        "dry_run": mode == "dry_run",
    }
    return dict(
        tool=TOOL, mode=mode, outcome=outcome, reason=reason,
        customer_id=args["customer_id"], order_id=args["order_id"], amount=amount,
        currency=facts.order["currency"] if facts and facts.order else None,
        clause_id=f"{doc} {cid}" if doc and cid else None,
        args={k: v for k, v in args.items() if v is not None},
    )


def _refuse(conn, req, amount, facts, mode, reason):
    audit.log(conn, **_audit_fields(req, amount, facts, mode, "refused", reason))
    return {"status": "refused", "reason": reason}


def dry_run_refund(conn, req: RefundRequest) -> dict:
    """Check the refund and, if it may go ahead, return a preview and a single-use token. Nothing is refunded."""
    amount = _amount(req)
    facts = _facts(conn, req)
    reason = policy.check_refund(req, facts)
    if reason:
        return _refuse(conn, req, amount, facts, "dry_run", reason)

    token = secrets.token_urlsafe(32)
    with _savepoint(conn, "dry_run"):
        expires_at = conn.execute(
            "insert into ops.confirm_tokens (token_hash, tool, args_hash, expires_at) "
            "values (%s, %s, %s, now() + make_interval(secs => %s::double precision)) returning expires_at",
            (_sha(token), TOOL, _args_hash(req, amount), float(config.CONFIRM_TOKEN_TTL_SECONDS)),
        ).fetchone()[0]
        audit.log(conn, **_audit_fields(req, amount, facts, "dry_run", "allowed"))

    cap = config.REFUND_CAP[facts.order["currency"]]
    return {
        "status": "preview",
        "token": token,
        "expires_at": expires_at.isoformat(),
        "refund": {
            "customer_id": req.customer_id, "order_id": req.order_id, "amount": format(amount, "f"),
            "currency": facts.order["currency"], "clause": f"{req.clause_doc} {req.clause_id}",
        },
        "cap_remaining_after": format(cap - (facts.refunded_by_customer + amount), "f"),
    }


def _check_token(conn, token, tool, expected_hash) -> str | None:
    if not token:
        return "token_missing"
    row = conn.execute(
        "select tool, args_hash, used_at, expires_at <= now() from ops.confirm_tokens where token_hash = %s",
        (_sha(token),),
    ).fetchone()
    if row is None or row[0] != tool:
        return "token_invalid"
    if row[2] is not None:
        return "token_used"
    if row[3]:
        return "token_expired"
    if expected_hash is None or row[1] != expected_hash:
        return "args_mismatch"
    return None


def commit_refund(conn, req: RefundRequest, token: str | None) -> dict:
    """Spend a token and record the refund, or refuse. The limits are checked again under a per-customer lock."""
    amount = _amount(req)
    facts = None
    try:
        with _savepoint(conn, "commit_refund"):
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(req.customer_id),))
            facts = _facts(conn, req)
            expected = None if amount is None else _args_hash(req, amount)
            reason = _check_token(conn, token, TOOL, expected) or policy.check_refund(req, facts)
            if reason:
                raise _Refusal(reason)
            spent = conn.execute(
                "update ops.confirm_tokens set used_at = now() where token_hash = %s and used_at is null "
                "returning token_hash", (_sha(token),),
            ).fetchone()
            if spent is None:
                raise _Refusal("token_used")
            refund_id = conn.execute(
                "insert into ops.refunds (order_id, customer_id, amount, currency, clause_doc, clause_id) "
                "values (%s, %s, %s, %s, %s, %s) returning refund_id",
                (req.order_id, req.customer_id, amount, facts.order["currency"], req.clause_doc, req.clause_id),
            ).fetchone()[0]
            audit.log(conn, **_audit_fields(req, amount, facts, "commit", "allowed"))
    except _Refusal as refusal:
        return _refuse(conn, req, amount, facts, "commit", refusal.reason)
    return {
        "status": "done", "refund_id": str(refund_id), "order_id": req.order_id,
        "amount": format(amount, "f"), "currency": facts.order["currency"],
    }


# ---------------------------------------------------------------------------------------------------------------
# cancel_subscription: the same two-step pattern, with no money involved.

def _cancel_facts(conn, req: CancelRequest) -> CancelFacts:
    row = conn.execute(
        "select order_id, customer_id, kind from orders where order_id = %s", (req.order_id,)
    ).fetchone()
    if row is None:
        return CancelFacts(None, False)
    done = conn.execute(
        "select exists (select 1 from ops.cancellations where order_id = %s)", (req.order_id,)
    ).fetchone()[0]
    return CancelFacts({"order_id": row[0], "customer_id": row[1], "kind": row[2]}, bool(done))


def _cancel_audit(req, mode, outcome, reason=None):
    doc, cid = _clean(req.clause_doc, _DOC), _clean(req.clause_id, _CLAUSE)
    args = {
        "customer_id": _clean(req.customer_id, _CUSTOMER),
        "order_id": _clean(req.order_id, _ORDER),
        "clause_doc": doc, "clause_id": cid, "dry_run": mode == "dry_run",
    }
    return dict(
        tool=CANCEL_TOOL, mode=mode, outcome=outcome, reason=reason,
        customer_id=args["customer_id"], order_id=args["order_id"],
        clause_id=f"{doc} {cid}" if doc and cid else None,
        args={k: v for k, v in args.items() if v is not None},
    )


def _cancel_refuse(conn, req, mode, reason):
    audit.log(conn, **_cancel_audit(req, mode, "refused", reason))
    return {"status": "refused", "reason": reason}


def dry_run_cancel(conn, req: CancelRequest) -> dict:
    """Check the cancellation and, if it may go ahead, return a preview and a single-use token. Nothing is cancelled."""
    reason = policy.check_cancel(req, _cancel_facts(conn, req))
    if reason:
        return _cancel_refuse(conn, req, "dry_run", reason)
    token = secrets.token_urlsafe(32)
    with _savepoint(conn, "dry_run"):
        expires_at = conn.execute(
            "insert into ops.confirm_tokens (token_hash, tool, args_hash, expires_at) "
            "values (%s, %s, %s, now() + make_interval(secs => %s::double precision)) returning expires_at",
            (_sha(token), CANCEL_TOOL, _cancel_hash(req), float(config.CONFIRM_TOKEN_TTL_SECONDS)),
        ).fetchone()[0]
        audit.log(conn, **_cancel_audit(req, "dry_run", "allowed"))
    return {
        "status": "preview", "token": token, "expires_at": expires_at.isoformat(),
        "cancellation": {"customer_id": req.customer_id, "order_id": req.order_id,
                         "clause": f"{req.clause_doc} {req.clause_id}"},
    }


def commit_cancel(conn, req: CancelRequest, token: str | None) -> dict:
    """Spend a token and record the cancellation, or refuse. Re-checked under the per-customer lock."""
    try:
        with _savepoint(conn, "commit_cancel"):
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(req.customer_id),))
            reason = (_check_token(conn, token, CANCEL_TOOL, _cancel_hash(req))
                      or policy.check_cancel(req, _cancel_facts(conn, req)))
            if reason:
                raise _Refusal(reason)
            spent = conn.execute(
                "update ops.confirm_tokens set used_at = now() where token_hash = %s and used_at is null "
                "returning token_hash", (_sha(token),),
            ).fetchone()
            if spent is None:
                raise _Refusal("token_used")
            cancellation_id = conn.execute(
                "insert into ops.cancellations (customer_id, order_id, clause_doc, clause_id) "
                "values (%s, %s, %s, %s) returning cancellation_id",
                (req.customer_id, req.order_id, req.clause_doc, req.clause_id),
            ).fetchone()[0]
            audit.log(conn, **_cancel_audit(req, "commit", "allowed"))
    except _Refusal as refusal:
        return _cancel_refuse(conn, req, "commit", refusal.reason)
    return {"status": "done", "cancellation_id": str(cancellation_id), "order_id": req.order_id}
