"""Billing contract: the case record, the step limit, the checks on what the model asks for, and the rules
that turn a tool result into an outcome. No model call, no database and no MCP client here.

The billing agent decides WHAT to do about a refund request. The model chooses which tool to call and
judges whether the policy is met. Code does everything that matters:

  * the customer id comes from the case (the caller), never from the message or from the model;
  * the model never sees or holds the confirmation token: code runs the dry run, then the commit;
  * the model cannot call a tool that is not on MODEL_TOOLS, and cannot make more than MAX_STEPS calls;
  * what happens after a dry run is decided by next_after_dry_run, from the tool's reason code, never from model text;
  * a refund over the cap is queued as a proposal for a person and never retried or argued.

The hard limits (cap, ownership, clause exists, token) stay in the MCP server. This file copies none of
them, so there is one place to change a limit.
"""
import re

from case import is_case_id

CUSTOMER_ID = re.compile(r"cust_[0-9]{3}")                 # ASCII digits only, used with fullmatch (ADR-047)
ORDER_ID = re.compile(r"ord_[0-9]{4}")
AMOUNT = re.compile(r"[0-9]{1,9}(\.[0-9]{1,2})?")
CLAUSE_PART = re.compile(r"[a-z0-9_.]{1,40}")              # a document such as tos_v3, a clause such as 2.2
LABEL = re.compile(r"[a-z_]{0,40}")                        # a reason code: lowercase words, never free text
ERROR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,59}")    # an exception class name, never its message

# What the model may ask for. request_refund is one tool to the model; code turns it into a dry run and a commit.
MODEL_TOOLS = ("search_policy", "get_order", "get_account", "request_refund", "close_case")
# The tool names a step may carry in the record: what actually ran.
STEP_TOOLS = ("search_policy", "get_order", "get_account", "issue_refund")
STEP_STATUS = ("ok", "preview", "done", "refused", "error")
STEP_MODES = ("", "dry_run", "commit")
MAX_STEPS = 8

OUTCOMES = ("settled", "queued", "refused", "needs_person")

# How the model itself may end a case with close_case: outcome -> the reasons it may give. Closed lists, no free text.
AGENT_CLOSES = {
    "refused": ("not_eligible",),
    "needs_person": ("needs_evidence", "missing_details", "not_supported"),
}

# A refusal the customer should simply be told about. Nobody needs to look at it.
CUSTOMER_REFUSALS = frozenset({
    "no_clause", "unknown_clause", "clause_not_allowed", "invalid_amount", "over_refundable",
    "order_not_found", "wrong_customer", "customer_not_found",
})
# A refusal that is a person's decision: the money is in scope, the limit is the reason.
QUEUE_REASONS = frozenset({"over_cap"})

PROPOSAL_SUMMARY = "Refund request over the cap: a person decides whether to refund {amount} on order {order_id}."


class StepLimitReached(Exception):
    """The agent used all its steps. The case ends as needs_person, never as a guess."""


class CaseRecord:
    """One record follows a case through the billing agent. It holds ids, labels and counts, never text."""

    def __init__(self, case_id: str, customer_id: str, intent: str = "", max_steps: int = MAX_STEPS):
        if not is_case_id(case_id):
            raise ValueError("case_id is not a server-made case id")
        if not (isinstance(customer_id, str) and CUSTOMER_ID.fullmatch(customer_id)):
            raise ValueError("customer_id does not match cust_ and three digits")
        if not (isinstance(max_steps, int) and not isinstance(max_steps, bool) and 1 <= max_steps <= 50):
            raise ValueError("max_steps must be a whole number from 1 to 50")
        self.case_id = case_id
        self.customer_id = customer_id
        self.intent = intent
        self.max_steps = max_steps
        self.steps: list[dict] = []
        self.outcome = ""
        self.reason = ""
        self.item_id = None
        self.error = ""

    def check_budget(self, count: int = 1) -> None:
        """Raise StepLimitReached if fewer than `count` steps are left. Call it BEFORE a tool runs."""
        if len(self.steps) + count > self.max_steps:
            raise StepLimitReached(f"fewer than {count} steps left of {self.max_steps}")

    def add_step(self, tool: str, status: str, reason: str = "", mode: str = "") -> dict:
        """Record one tool call that is about to count, or that just ran. Refuses the call past the limit."""
        if self.outcome:
            raise ValueError("the case is already finished")
        if tool not in STEP_TOOLS:
            raise ValueError(f"tool {tool!r} is not one the billing agent may use")
        if status not in STEP_STATUS:
            raise ValueError(f"status {status!r} is not allowed")
        if mode not in STEP_MODES:
            raise ValueError(f"mode {mode!r} is not allowed")
        if not (isinstance(reason, str) and LABEL.fullmatch(reason)):
            raise ValueError("reason must be a lowercase code, never free text")
        if len(self.steps) >= self.max_steps:
            raise StepLimitReached(f"more than {self.max_steps} steps")
        step = {"n": len(self.steps) + 1, "tool": tool, "mode": mode, "status": status, "reason": reason}
        self.steps.append(step)
        return step

    def finish(self, outcome: str, reason: str = "", item_id=None, error: str = "") -> None:
        if self.outcome:
            raise ValueError("the case is already finished")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome {outcome!r} is not allowed")
        if not (isinstance(reason, str) and LABEL.fullmatch(reason)):
            raise ValueError("reason must be a lowercase code, never free text")
        if outcome == "queued" and item_id is None:
            raise ValueError("a queued case needs the id of its queue item")
        if outcome != "queued" and item_id is not None:
            raise ValueError("only a queued case has a queue item")
        if outcome != "settled" and not reason:
            raise ValueError("an outcome that is not settled needs a reason code")
        if error and not (isinstance(error, str) and ERROR_NAME.fullmatch(error)):
            raise ValueError("error must be an exception class name, never its message")
        self.outcome, self.reason, self.item_id = outcome, reason, (None if item_id is None else str(item_id))
        self.error = error

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id, "customer_id": self.customer_id, "intent": self.intent,
            "steps": [dict(s) for s in self.steps], "outcome": self.outcome, "reason": self.reason,
            "item_id": self.item_id, "error": self.error,
        }

    def trace_fields(self) -> dict:
        """What may go into a trace: labels and counts. No message text, no token, no amount."""
        return {"billing_outcome": self.outcome, "billing_reason": self.reason,
                "billing_steps": len(self.steps), "billing_queued": self.outcome == "queued",
                "billing_error": self.error}


def refund_args_problems(args) -> list[tuple[str, str]]:
    """(field, reason) for everything wrong with what the model asked request_refund to do.

    The model may give exactly four things. The customer id, the dry run flag and the token are not its to
    give: a model that sends them is refused, so a message cannot talk it into refunding someone else.
    """
    if not isinstance(args, dict):
        return [("shape", "arguments are not an object")]
    allowed = {"order_id", "amount", "clause_doc", "clause_id"}
    out = []
    for extra in sorted(set(args) - allowed):
        out.append((extra, "this argument is not the model's to give"))
    if "order_id" not in args or "amount" not in args:
        out.append(("shape", "order_id and amount are required"))
    o = args.get("order_id")
    if "order_id" in args and not (isinstance(o, str) and ORDER_ID.fullmatch(o)):
        out.append(("order_id", "order_id does not match ord_ and four digits"))
    a = args.get("amount")
    if "amount" in args and not (isinstance(a, str) and AMOUNT.fullmatch(a)):
        out.append(("amount", "amount is not plain digits with up to two decimals"))
    for key in ("clause_doc", "clause_id"):
        v = args.get(key)
        if v is not None and not (isinstance(v, str) and CLAUSE_PART.fullmatch(v)):
            out.append((key, f"{key} is not a plain document or clause label"))
    return out


def close_case_problems(args) -> list[tuple[str, str]]:
    """(field, reason) for everything wrong with the model's close_case call. It may give an outcome and a reason, nothing else."""
    if not isinstance(args, dict):
        return [("shape", "arguments are not an object")]
    out = [(k, "this argument is not the model's to give") for k in sorted(set(args) - {"outcome", "reason"})]
    outcome, reason = args.get("outcome"), args.get("reason")
    if outcome not in AGENT_CLOSES:
        out.append(("outcome", "the model may close a case only as refused or needs_person"))
    elif reason not in AGENT_CLOSES[outcome]:
        out.append(("reason", f"reason is not one of the allowed reasons for {outcome}"))
    return out


def next_after_dry_run(result) -> tuple[str, str]:
    """What code does after the dry run: ("commit", ""), ("queue", reason), ("refused", reason) or ("needs_person", reason).

    Only the status and the reason code of the tool result are read. Anything unexpected is needs_person,
    because a result nobody planned for is not one to act on.
    """
    if not isinstance(result, dict):
        return "needs_person", "unexpected_result"
    status, reason = result.get("status"), result.get("reason")
    if status == "preview":
        token = result.get("token")
        if isinstance(token, str) and token:
            return "commit", ""
        return "needs_person", "unexpected_result"
    if status == "refused" and isinstance(reason, str) and LABEL.fullmatch(reason):
        if reason in QUEUE_REASONS:
            return "queue", reason
        if reason in CUSTOMER_REFUSALS:
            return "refused", reason
        return "needs_person", reason or "unexpected_result"
    return "needs_person", "unexpected_result"


def outcome_after_commit(result) -> tuple[str, str]:
    """The case outcome after the commit call: ("settled", ""), ("queued", reason), ("refused", reason) or ("needs_person", reason).

    A cap that fills up between the dry run and the commit comes back as over_cap and is queued like any
    other refund over the cap. A token problem is a fault in our own flow, not the customer's, so a person looks.
    """
    if not isinstance(result, dict):
        return "needs_person", "unexpected_result"
    status, reason = result.get("status"), result.get("reason")
    if status == "done" and result.get("refund_id"):
        return "settled", ""
    if status == "refused" and isinstance(reason, str) and LABEL.fullmatch(reason):
        if reason in QUEUE_REASONS:
            return "queued", reason
        if reason in CUSTOMER_REFUSALS:
            return "refused", reason
        return "needs_person", reason or "unexpected_result"
    return "needs_person", "unexpected_result"


def refund_proposal(case_id: str, customer_id: str, question: str, args: dict) -> dict:
    """Arguments for review.enqueue_action: a refund a person must decide. It proposes; it never refunds.

    The args hold only ids, the amount and the clause, so whoever approves it can see exactly what would run.
    The summary is built from fixed words and validated values, never from model text.
    """
    if not is_case_id(case_id) or not CUSTOMER_ID.fullmatch(customer_id or ""):
        raise ValueError("case_id or customer_id is not valid")
    if refund_args_problems(args):
        raise ValueError("the refund arguments are not valid")
    return {
        "case_id": case_id,
        "question": question,
        "summary": PROPOSAL_SUMMARY.format(amount=args["amount"], order_id=args["order_id"]),
        "tool": "issue_refund",
        "args": {"customer_id": customer_id, "order_id": args["order_id"], "amount": args["amount"],
                 "clause_doc": args.get("clause_doc"), "clause_id": args.get("clause_id")},
    }
