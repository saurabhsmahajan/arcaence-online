"""Audit log writer. Every attempt of a write tool is recorded, allowed or refused. Fails closed."""
from decimal import Decimal

from psycopg.types.json import Jsonb

import config
import db_write

MODES = {"dry_run", "commit"}
OUTCOMES = {"allowed", "refused", "error"}

# A closed list: a refusal must say why, in one of these words, never in free text.
REASONS = {
    "no_clause",
    "unknown_clause",
    "clause_not_allowed",
    "invalid_amount",
    "over_cap",
    "over_refundable",
    "order_not_found",
    "wrong_customer",
    "customer_not_found",
    "subscription_not_active",
    "token_missing",
    "token_invalid",
    "token_expired",
    "token_used",
    "args_mismatch",
    "request_already_open",
    "no_open_request",
    "internal_error",
}

# Only these argument names may be stored. Anything else (an email, a free-text note) is refused.
ARG_KEYS = {"customer_id", "order_id", "amount", "currency", "clause_doc", "clause_id", "dry_run"}

_INSERT = (
    "insert into ops.audit_log "
    "(server_role, tool, mode, outcome, reason, customer_id, order_id, amount, currency, clause_id, args) "
    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


class AuditError(Exception):
    """The audit row could not be written or was malformed. The caller must not go ahead with the action."""


def _validate(tool, mode, outcome, reason, args):
    if not tool:
        raise AuditError("tool is required")
    if mode not in MODES:
        raise AuditError(f"unknown mode {mode!r}")
    if outcome not in OUTCOMES:
        raise AuditError(f"unknown outcome {outcome!r}")
    if outcome in ("refused", "error") and reason is None:
        raise AuditError("a refused or failed attempt must carry a reason code")
    if reason is not None and reason not in REASONS:
        raise AuditError(f"unknown reason code {reason!r}")
    extra = set(args or {}) - ARG_KEYS
    if extra:
        raise AuditError(f"argument fields not allowed in the audit log: {sorted(extra)}")


def log(conn, *, tool, mode, outcome, reason=None, customer_id=None, order_id=None,
        amount=None, currency=None, clause_id=None, args=None):
    """Write one audit row on the caller's connection, so it commits or rolls back with the caller's work."""
    _validate(tool, mode, outcome, reason, args)
    if amount is not None and not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    conn.execute(
        _INSERT,
        (config.ROLE, tool, mode, outcome, reason, customer_id, order_id, amount, currency, clause_id,
         Jsonb(args) if args is not None else None),
    )


def log_standalone(**fields):
    """Write one audit row in its own transaction. Used for refusals and dry runs."""
    try:
        with db_write.connect() as conn:
            log(conn, **fields)
    except AuditError:
        raise
    except Exception as e:  # noqa: BLE001
        raise AuditError("audit write failed") from e
