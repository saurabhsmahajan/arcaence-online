"""The billing agent in shadow mode: it runs on a real message and records what it WOULD have done.

Shadow means three things, all kept by code and checked by tests:
  - the database is never changed: every run is one case on the rolled-back adapter (billing_tools.LocalTools);
  - nothing reaches the review queue: a proposal the agent makes is kept in memory and thrown away;
  - the customer's reply is never changed: the handler only records the outcome and a preview of the words.

BILLING_MODE=shadow turns it on. Any other value, or none, is off. There is no "live" here on purpose:
going live is a different change, made after the shadow runs show the agent is safe on real messages.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from billing import run_billing

ROOT = Path(__file__).resolve().parent.parent


class Watch:
    """Wraps the tools and notes every commit that went through, so a result reads what happened to the money."""

    def __init__(self, tools):
        self._tools, self.commits = tools, []

    def get_order(self, order_id):
        return self._tools.get_order(order_id)

    def get_account(self, customer_id):
        return self._tools.get_account(customer_id)

    def search_policy(self, query):
        return self._tools.search_policy(query)

    def issue_refund(self, customer_id, order_id, amount, clause_doc, clause_id, dry_run, confirm_token):
        result = self._tools.issue_refund(customer_id, order_id, amount, clause_doc, clause_id, dry_run, confirm_token)
        if not dry_run:
            res = result if isinstance(result, dict) else {}
            self.commits.append({"status": res.get("status"), "reason": res.get("reason"), "amount": res.get("amount"),
                                 "currency": res.get("currency"), "order_id": res.get("order_id"),
                                 "clause": f"{clause_doc} {clause_id}"})
        return result


class Queue:
    """Stands in for the review queue: keeps what would have been queued and hands back an id."""

    def __init__(self):
        self.items = []

    def __call__(self, proposal):
        self.items.append(proposal)
        return len(self.items)


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def shadow_billing(question, case_id, customer_id, tools, create_fn=None, today=None) -> dict:
    """One shadow run. `tools` has a case() context manager that always rolls back (LocalTools).
    Returns {"record": CaseRecord dict, "refund": the commit that would have been recorded or None, "proposals": [...]}.
    The customer id comes from the caller, never from the message; the date comes from code."""
    watched, queue = Watch(tools), Queue()
    with tools.case():
        rec = run_billing(question, case_id, customer_id, today or utc_today(), watched, queue, create_fn=create_fn)
    refund = next((c for c in watched.commits if c.get("status") == "done"), None)
    return {"record": rec.to_dict(), "refund": refund, "proposals": queue.items}


def default_billing_fn(mcp_dir=None):
    """The function the handler calls, or None when shadow mode is off. Read at each call, not at import."""
    if os.environ.get("BILLING_MODE") != "shadow":
        return None

    def run(question, case_id, customer_id):
        from billing_tools import local_tools   # a fresh adapter per request: one connection is never shared

        return shadow_billing(question, case_id, customer_id, local_tools(mcp_dir or ROOT / "mcp"))

    return run
