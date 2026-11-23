"""Privacy requests. The AI can ask; a human decides. Nothing here sends, exports or deletes personal data.
Each function runs on the caller's connection, so its work and its audit row commit or roll back together."""
import psycopg

import audit
from actions import _savepoint

# The clause that lets a customer ask for a copy of their data or for it to be deleted. Recorded on every request.
PRIVACY_CLAUSE = "tos_v3 5.2"
EXPORT_TOOL = "request_data_export"
DELETE_TOOL = "request_account_deletion"
CANCEL_TOOL = "cancel_deletion_request"


def _refuse(conn, tool, customer_id, reason):
    audit.log(conn, tool=tool, mode="commit", outcome="refused", reason=reason,
              customer_id=customer_id, clause_id=PRIVACY_CLAUSE, args={"customer_id": customer_id})
    return {"status": "refused", "reason": reason}


def _allowed(conn, tool, customer_id):
    audit.log(conn, tool=tool, mode="commit", outcome="allowed", customer_id=customer_id,
              clause_id=PRIVACY_CLAUSE, args={"customer_id": customer_id})


def _customer_exists(conn, customer_id) -> bool:
    return conn.execute("select 1 from customers where customer_id = %s", (customer_id,)).fetchone() is not None


def request_export(conn, customer_id: str) -> dict:
    """Open an export request for one customer. Returns what the export would contain, as counts only."""
    if not _customer_exists(conn, customer_id):
        return _refuse(conn, EXPORT_TOOL, customer_id, "customer_not_found")

    try:
        with _savepoint(conn, "export_request"):
            request_id = conn.execute(
                "insert into ops.export_requests (customer_id) values (%s) returning request_id", (customer_id,)
            ).fetchone()[0]
            inventory = {
                "orders": conn.execute("select count(*) from orders where customer_id = %s", (customer_id,)).fetchone()[0],
                "invoices": conn.execute("select count(*) from invoices where customer_id = %s", (customer_id,)).fetchone()[0],
            }
            _allowed(conn, EXPORT_TOOL, customer_id)
    except psycopg.errors.UniqueViolation:
        return _refuse(conn, EXPORT_TOOL, customer_id, "request_already_open")

    return {
        "status": "requested",
        "kind": "export",
        "request_id": str(request_id),
        "inventory": inventory,
        "next_step": "A person confirms the customer's identity and then sends the copy. Nothing is sent by this tool.",
    }


def request_deletion(conn, customer_id: str) -> dict:
    """Open a deletion request. It always ends here, as 'requested': a person approves, then a waiting
    period runs, then a person completes it. This function has no path to any later state."""
    if not _customer_exists(conn, customer_id):
        return _refuse(conn, DELETE_TOOL, customer_id, "customer_not_found")

    try:
        with _savepoint(conn, "deletion_request"):
            request_id = conn.execute(
                "insert into ops.deletion_requests (customer_id) values (%s) returning request_id", (customer_id,)
            ).fetchone()[0]
            _allowed(conn, DELETE_TOOL, customer_id)
    except psycopg.errors.UniqueViolation:
        return _refuse(conn, DELETE_TOOL, customer_id, "request_already_open")

    return {
        "status": "requested",
        "kind": "deletion",
        "request_id": str(request_id),
        "next_step": ("Nothing has been deleted. A person must approve this request, then a 7-day waiting "
                      "period runs, during which it can be cancelled, and only then can a person complete it."),
    }


def cancel_deletion(conn, customer_id: str) -> dict:
    """Stop an open deletion request (still waiting for approval, or approved and in its waiting period)."""
    if not _customer_exists(conn, customer_id):
        return _refuse(conn, CANCEL_TOOL, customer_id, "customer_not_found")

    with _savepoint(conn, "deletion_cancel"):
        row = conn.execute(
            "update ops.deletion_requests set status = 'cancelled', cancelled_by = %s "
            "where customer_id = %s and status in ('requested', 'approved') returning request_id",
            (f"tool:{CANCEL_TOOL}", customer_id),
        ).fetchone()
        if row is not None:
            _allowed(conn, CANCEL_TOOL, customer_id)
    if row is None:
        return _refuse(conn, CANCEL_TOOL, customer_id, "no_open_request")

    return {
        "status": "cancelled",
        "kind": "deletion",
        "request_id": str(row[0]),
        "next_step": "The deletion request is cancelled. Nothing was deleted.",
    }
