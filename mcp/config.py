"""Role is decided once, at process start, from the environment. Nothing at call time can change it.
Policy limits for the write tools live here too, as plain data that a reviewer can read."""
import os
from decimal import Decimal

ROLE_TOOLS: dict[str, frozenset[str]] = {
    "ops_reader": frozenset({"get_account", "get_order", "get_subscription"}),
    # The writer role has no read tools: it cannot see raw contact data, and agents read through the reader server.
    "ops_writer": frozenset({"issue_refund", "cancel_subscription"}),
}

ROLE: str = os.environ.get("OPS_ROLE", "ops_reader")
if ROLE not in ROLE_TOOLS:
    raise SystemExit(f"Unknown OPS_ROLE {ROLE!r}. Allowed: {sorted(ROLE_TOOLS)}")
ALLOWED_TOOLS: frozenset[str] = ROLE_TOOLS[ROLE]

# --- Write-tool policy limits (synthetic values; change them here and nowhere else) ---

# Most one customer may be refunded through the desk, in total, per currency. Above it a human decides.
REFUND_CAP: dict[str, Decimal] = {
    "EUR": Decimal("50.00"),
    "USD": Decimal("55.00"),
    "INR": Decimal("4500.00"),
}

# A write must cite a clause from an approved document, and the clause must be a real basis for that action.
# Superseded and draft documents are not on these lists, even though their ids exist in the frozen registry.
REFUND_CLAUSES: frozenset[tuple[str, str]] = frozenset({
    ("tos_v3", "2.2"),       # refund of a one-off purchase within 7 days, not downloaded
    ("tos_v3", "2.4"),       # cancel an order before delivery, full refund
    ("tos_v3", "3.3"),       # refund of an unintended renewal within 7 days
    ("consumer_act", "3.2"), # statutory refund for a serious defect
})
CANCEL_CLAUSES: frozenset[tuple[str, str]] = frozenset({
    ("tos_v3", "3.2"),       # cancel a subscription at least 24 hours before renewal
    ("tos_v3", "6.3"),       # close an account at any time
})

# A confirmation token from a dry run is valid for this many seconds, and for one commit only.
CONFIRM_TOKEN_TTL_SECONDS: int = 600
