"""Privacy contract: the case record, the step limit, the checks on what the model asks for, and the rules
that turn a tool result into an outcome. No model call, no database and no MCP client here.

The privacy agent decides WHICH privacy request, if any, a customer is making. The model reads the message
and chooses one tool or closes the case. Code does everything that matters:

  * the customer id comes from the case (the caller), never from the message or from the model;
  * the model gives NO arguments to a privacy tool. The tool takes only the customer id, which code supplies;
  * the model cannot call a tool that is not on MODEL_TOOLS, and cannot make more than MAX_STEPS tool calls;
  * the outcome after a tool call is decided by outcome_after_tool, from the tool's status and reason code,
    never from model text;
  * a request is only ever OPENED or CANCELLED here. Nothing is deleted, sent or exported by these tools:
    a person approves a deletion, a 7-day wait runs, and a person completes it (migration 010).

The one-action-per-case rule is on purpose. The privacy tools return nothing the model needs to reason about
next, so the case ends when a tool has run.
"""
import re

from case import is_case_id

CUSTOMER_ID = re.compile(r"cust_[0-9]{3}")                 # ASCII digits only, used with fullmatch (ADR-047)
LABEL = re.compile(r"[a-z_]{0,40}")                        # a reason code: lowercase words, never free text
ERROR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,59}")    # an exception class name, never its message
REQUEST_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# The tools that open or cancel a request. Each takes only the customer id, which code supplies.
ACTION_TOOLS = ("request_data_export", "request_account_deletion", "cancel_deletion_request")
# What the model may ask for. close_case lets it end a case without any request.
MODEL_TOOLS = ACTION_TOOLS + ("close_case",)
# The tool names a step may carry in the record: what actually ran.
STEP_TOOLS = ACTION_TOOLS
STEP_STATUS = ("ok", "refused", "error")
MAX_STEPS = 1

OUTCOMES = ("requested", "cancelled", "refused", "needs_person")
TOOL_KIND = {"request_data_export": "export", "request_account_deletion": "deletion",
             "cancel_deletion_request": "deletion"}

# How the model itself may end a case with close_case: outcome -> the reasons it may give. Closed lists, no free text.
AGENT_CLOSES = {
    "refused": ("not_eligible",),                           # a request about someone else's account
    "needs_person": ("unclear_request", "not_supported"),   # a question, an unclear message, or a right no tool covers
}
# What a privacy tool may refuse with, and the customer should simply be told.
TOOL_REFUSALS = frozenset({"request_already_open", "no_open_request", "customer_not_found"})
# Every reason a case may end with, by outcome. Anything else is refused by CaseRecord.finish.
ALLOWED_REASONS = {
    "refused": frozenset(AGENT_CLOSES["refused"]) | TOOL_REFUSALS,
    "needs_person": frozenset(AGENT_CLOSES["needs_person"]) | {"unexpected_result", "step_limit", "tool_error"},
}
INVENTORY_KEYS = ("orders", "invoices")


class StepLimitReached(Exception):
    """The agent asked for more tool calls than it may make. The case ends as needs_person, never as a guess."""


def clean_inventory(value):
    """The export counts, or None. Exactly the two known keys, each a whole number. Never the data itself."""
    if not (isinstance(value, dict) and set(value) == set(INVENTORY_KEYS)):
        return None
    out = {}
    for key in INVENTORY_KEYS:
        v = value[key]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 1_000_000:
            return None
        out[key] = v
    return out


class CaseRecord:
    """One record follows a case through the privacy agent. It holds ids, labels and counts, never text."""

    def __init__(self, case_id: str, customer_id: str, intent: str = "", max_steps: int = MAX_STEPS):
        if not is_case_id(case_id):
            raise ValueError("case_id is not a server-made case id")
        if not (isinstance(customer_id, str) and CUSTOMER_ID.fullmatch(customer_id)):
            raise ValueError("customer_id does not match cust_ and three digits")
        if not (isinstance(max_steps, int) and not isinstance(max_steps, bool) and 1 <= max_steps <= 10):
            raise ValueError("max_steps must be a whole number from 1 to 10")
        self.case_id = case_id
        self.customer_id = customer_id
        self.intent = intent
        self.max_steps = max_steps
        self.steps: list[dict] = []
        self.outcome = ""
        self.reason = ""
        self.request_id = None
        self.inventory = None
        self.error = ""

    @property
    def kind(self) -> str:
        """export or deletion, from the tool that ran. Empty when no tool ran."""
        return TOOL_KIND[self.steps[-1]["tool"]] if self.steps else ""

    def check_budget(self, count: int = 1) -> None:
        """Raise StepLimitReached if fewer than `count` steps are left. Call it BEFORE a tool runs."""
        if len(self.steps) + count > self.max_steps:
            raise StepLimitReached(f"fewer than {count} steps left of {self.max_steps}")

    def add_step(self, tool: str, status: str, reason: str = "") -> dict:
        """Record one tool call that is about to count, or that just ran. Refuses the call past the limit."""
        if self.outcome:
            raise ValueError("the case is already finished")
        if tool not in STEP_TOOLS:
            raise ValueError(f"tool {tool!r} is not one the privacy agent may use")
        if status not in STEP_STATUS:
            raise ValueError(f"status {status!r} is not allowed")
        if not (isinstance(reason, str) and LABEL.fullmatch(reason)):
            raise ValueError("reason must be a lowercase code, never free text")
        if len(self.steps) >= self.max_steps:
            raise StepLimitReached(f"more than {self.max_steps} steps")
        step = {"n": len(self.steps) + 1, "tool": tool, "status": status, "reason": reason}
        self.steps.append(step)
        return step

    def finish(self, outcome: str, reason: str = "", request_id=None, inventory=None, error: str = "") -> None:
        if self.outcome:
            raise ValueError("the case is already finished")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome {outcome!r} is not allowed")
        if not (isinstance(reason, str) and LABEL.fullmatch(reason)):
            raise ValueError("reason must be a lowercase code, never free text")
        if error and not (isinstance(error, str) and ERROR_NAME.fullmatch(error)):
            raise ValueError("error must be an exception class name, never its message")
        if outcome in ("requested", "cancelled"):
            if reason:
                raise ValueError("a requested or cancelled case has no reason code")
            if not self.steps:
                raise ValueError("a requested or cancelled case needs the tool call that did it")
            tool = self.steps[-1]["tool"]
            if (outcome == "cancelled") != (tool == "cancel_deletion_request"):
                raise ValueError("the outcome does not match the tool that ran")
            if not (isinstance(request_id, str) and REQUEST_ID.fullmatch(request_id)):
                raise ValueError("a requested or cancelled case needs the id of its request")
            if tool == "request_data_export":
                inventory = clean_inventory(inventory)
                if inventory is None:
                    raise ValueError("an export request needs its counts")
            elif inventory is not None:
                raise ValueError("only an export request has counts")
        else:
            if reason not in ALLOWED_REASONS[outcome]:
                raise ValueError(f"reason {reason!r} is not allowed for {outcome}")
            if request_id is not None or inventory is not None:
                raise ValueError("only a requested or cancelled case has a request")
        self.outcome, self.reason, self.error = outcome, reason, error
        self.request_id = None if request_id is None else str(request_id)
        self.inventory = inventory

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id, "customer_id": self.customer_id, "intent": self.intent,
            "steps": [dict(s) for s in self.steps], "outcome": self.outcome, "reason": self.reason,
            "kind": self.kind, "request_id": self.request_id,
            "inventory": None if self.inventory is None else dict(self.inventory), "error": self.error,
        }

    def trace_fields(self) -> dict:
        """What may go into a trace: labels and counts. No message text, no customer id, no request id."""
        return {"privacy_outcome": self.outcome, "privacy_reason": self.reason, "privacy_kind": self.kind,
                "privacy_steps": len(self.steps), "privacy_error": self.error}


def tool_args_problems(tool, args) -> list[tuple[str, str]]:
    """(field, reason) for everything wrong with what the model asked a privacy tool to do.

    The model gives no arguments at all. A model that sends a customer id is refused, so a message cannot
    talk it into opening a request for someone else.
    """
    if tool not in ACTION_TOOLS:
        return [("tool", "this is not a privacy tool the model may call")]
    if args is None or args == {}:
        return []
    if not isinstance(args, dict):
        return [("shape", "arguments are not an object")]
    return [(k, "this argument is not the model's to give") for k in sorted(args)]


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


def outcome_after_tool(tool, result) -> dict:
    """What the case outcome is after a privacy tool ran: {"outcome", "reason", "request_id", "inventory"}.

    Only the status, the kind, the reason code, the request id and the export counts of the tool result are
    read. Anything unexpected is needs_person, because a result nobody planned for is not one to act on.
    """
    bad = {"outcome": "needs_person", "reason": "unexpected_result", "request_id": None, "inventory": None}
    if tool not in ACTION_TOOLS or not isinstance(result, dict):
        return bad
    status, reason = result.get("status"), result.get("reason")
    if status == "refused":
        if isinstance(reason, str) and reason in TOOL_REFUSALS:
            return {"outcome": "refused", "reason": reason, "request_id": None, "inventory": None}
        return bad
    expected = "cancelled" if tool == "cancel_deletion_request" else "requested"
    if status != expected or result.get("kind") != TOOL_KIND[tool]:
        return bad
    request_id = result.get("request_id")
    if not (isinstance(request_id, str) and REQUEST_ID.fullmatch(request_id)):
        return bad
    inventory = None
    if tool == "request_data_export":
        inventory = clean_inventory(result.get("inventory"))
        if inventory is None:
            return bad
    return {"outcome": expected, "reason": "", "request_id": request_id, "inventory": inventory}
