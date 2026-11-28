"""The privacy agent in shadow mode: it runs on a real message and records what it WOULD have done.

Shadow means three things, all kept by code and checked by tests (the same three as billing):
  - the database is never changed: every run is one case on the rolled-back adapter (privacy_tools.PrivacyLocalTools),
    so a request the agent opens is rolled back with its audit row;
  - nothing reaches the review queue;
  - the customer's reply is never changed: the handler only records the outcome and a preview of the words.

What the agent WOULD have done is read from the request tables (a snapshot before and after), not from what the agent
said, the same rule the scorer uses.

PRIVACY_MODE=shadow turns it on. Any other value, or none, is off. There is no "live" here on purpose.
"""
import os
from pathlib import Path

from privacy_agent import run_privacy
from privacy_scoring import effects
from privacy_tools import PrivacyWatch

ROOT = Path(__file__).resolve().parent.parent


def shadow_privacy(question, case_id, customer_id, tools, create_fn=None, setup="none") -> dict:
    """One shadow run. `tools` has case() and snapshot() (PrivacyLocalTools), and case() always rolls back.
    `setup` (none, open_deletion, open_export) is for the desk cases only: it opens a request first, inside the same
    rolled-back transaction, so a "cancel" or "duplicate" case has something to meet. The handler never passes it.
    Returns {"record": CaseRecord dict, "effects": what would have changed, "calls": the tool calls made}.
    The customer id comes from the caller, never from the message."""
    watched = PrivacyWatch(tools)
    with tools.case(setup, customer_id):
        before = tools.snapshot()
        rec = run_privacy(question, case_id, customer_id, watched, create_fn=create_fn)
        fx = effects(before, tools.snapshot())
    return {"record": rec.to_dict(), "effects": fx, "calls": watched.calls}


def default_privacy_fn(mcp_dir=None):
    """The function the handler calls, or None when shadow mode is off. Read at each call, not at import."""
    if os.environ.get("PRIVACY_MODE") != "shadow":
        return None

    def run(question, case_id, customer_id):
        from privacy_tools import local_privacy_tools   # a fresh adapter per request: one connection is never shared

        return shadow_privacy(question, case_id, customer_id, local_privacy_tools(mcp_dir or ROOT / "mcp"))

    return run
