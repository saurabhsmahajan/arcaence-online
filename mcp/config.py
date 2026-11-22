"""Role is decided once, at process start, from the environment. Nothing at call time can change it."""
import os

ROLE_TOOLS: dict[str, frozenset[str]] = {
    "ops_reader": frozenset({"get_account", "get_order", "get_subscription"}),
}

ROLE: str = os.environ.get("OPS_ROLE", "ops_reader")
if ROLE not in ROLE_TOOLS:
    raise SystemExit(f"Unknown OPS_ROLE {ROLE!r}. Allowed: {sorted(ROLE_TOOLS)}")
ALLOWED_TOOLS: frozenset[str] = ROLE_TOOLS[ROLE]
