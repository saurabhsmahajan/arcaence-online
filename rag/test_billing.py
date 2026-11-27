"""Tests for the billing agent loop. A scripted fake model and fake tools: no real model, no database, no keys."""
import copy
import json

import billing
from billing import MAX_RESULT_CHARS, MAX_TURNS, TOOLS, run_billing
from billing_logic import AGENT_CLOSES, MODEL_TOOLS

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


CASE = "case_20261127_0123456789ab"
CUST = "cust_001"
TOKEN = "s3cret-token-value"
MESSAGE = "Please refund 19.00 EUR on ord_1001, I renewed by mistake."


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items() if v is not None}


def use(i, name, **inp):
    return Block(type="tool_use", id=f"tu_{i}", name=name, input=inp)


class Reply:
    def __init__(self, *blocks, stop="tool_use"):
        self.content, self.stop_reason = list(blocks), stop


class Model:
    """Returns scripted replies in order and keeps a copy of everything it was sent. An Exception is raised."""

    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def __call__(self, **kw):
        self.sent.append(copy.deepcopy(kw))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


ORDERS = {
    "ord_1001": {"order_id": "ord_1001", "customer_id": "cust_001", "item": "Pro plan, monthly", "kind": "subscription",
                 "amount": "19.00", "currency": "EUR", "purchased_at": "2026-11-01", "downloaded": False},
    "ord_2001": {"order_id": "ord_2001", "customer_id": "cust_002", "item": "SECRET Team plan, annual", "kind": "subscription",
                 "amount": "540.00", "currency": "USD", "purchased_at": "2026-09-15", "downloaded": False},
}
PREVIEW = {"status": "preview", "token": TOKEN}
DONE = {"status": "done", "refund_id": "r-1", "order_id": "ord_1001", "amount": "19.00", "currency": "EUR"}


class Tools:
    def __init__(self, *refund_results, fail=None):
        self.refund_results, self.fail, self.log = list(refund_results), fail, []

    def get_order(self, order_id):
        self.log.append(("get_order", order_id))
        if self.fail == "get_order":
            raise TimeoutError("db slow")
        return ORDERS.get(order_id)

    def get_account(self, customer_id):
        self.log.append(("get_account", customer_id))
        return {"customer_id": customer_id, "plan": "Pro", "currency": "EUR", "status": "active"}

    def search_policy(self, query):
        self.log.append(("search_policy", query))
        return {"results": [{"doc": "tos_v3", "clause": "3.3", "text": "x" * 9000}]}

    def issue_refund(self, **kw):
        self.log.append(("issue_refund", kw["dry_run"], kw["customer_id"]))
        r = self.refund_results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Queue:
    def __init__(self, item_id=5):
        self.item_id, self.items = item_id, []

    def __call__(self, proposal):
        self.items.append(proposal)
        return self.item_id


def run(model, tools=None, queue=None, **kw):
    return run_billing(MESSAGE, CASE, CUST, "2026-11-05", tools or Tools(), queue or Queue(), create_fn=model, **kw)


def tool_results(model, call_index):
    """The tool_result blocks that were sent in the model's call number call_index (0 based)."""
    msgs = model.sent[call_index]["messages"]
    return [b for m in msgs if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]]


# --- the tool list the model is given ----------------------------------------------------------------------
check([t["name"] for t in TOOLS] == list(MODEL_TOOLS), "the model is given exactly the billing tools")
check(all(t["input_schema"]["additionalProperties"] is False for t in TOOLS), "no tool accepts extra arguments")
props = {t["name"]: t["input_schema"]["properties"] for t in TOOLS}
check("customer_id" not in str(props) and "confirm_token" not in str(props) and "dry_run" not in str(props),
      "no tool lets the model give a customer id, a token or a dry run flag")
check(props["close_case"]["outcome"]["enum"] == sorted(AGENT_CLOSES), "close_case offers only the outcomes the model may use")
check(set(props["close_case"]["reason"]["enum"]) == {"not_eligible", "needs_evidence", "missing_details", "not_supported"}, "close_case offers the four reasons")
check("settled" not in str(props["close_case"]) and "queued" not in str(props["close_case"]), "the model cannot close a case as settled or queued")

# --- a refund that goes through ----------------------------------------------------------------------------
m = Model(Reply(use(1, "get_order", order_id="ord_1001")),
          Reply(use(2, "search_policy", query="refund of an unintended renewal")),
          Reply(use(3, "request_refund", order_id="ord_1001", amount="19.00", clause_doc="tos_v3", clause_id="3.3")))
t, q = Tools(PREVIEW, DONE), Queue()
r = run(m, t, q)
check(r.outcome == "settled" and r.reason == "", "a valid request is settled")
check([s["tool"] for s in r.steps] == ["get_order", "search_policy", "issue_refund", "issue_refund"], "the steps are the tools that ran")
check(t.log[-2:] == [("issue_refund", True, CUST), ("issue_refund", False, CUST)], "code runs the dry run then the commit with the case's customer")
check(len(m.sent) == 3, "three model turns")
check("2026-11-05" in m.sent[0]["system"], "the date is in the system prompt")
check(m.sent[0]["messages"][0]["content"] == f"Customer message: {MESSAGE}", "the message is sent as the customer's message")
check(TOKEN not in json.dumps(m.sent) and TOKEN not in str(r.to_dict()), "the model never sees the token and the record never holds it")
check("customer_id" not in tool_results(m, 1)[0]["content"], "the model's view of an order has no customer id")
check(r.steps[0]["status"] == "ok" and q.items == [], "nothing is queued")

# --- a refund over the cap goes to a person ----------------------------------------------------------------
m = Model(Reply(use(1, "get_order", order_id="ord_1001")),
          Reply(use(2, "request_refund", order_id="ord_1001", amount="19.00", clause_doc="tos_v3", clause_id="3.3")))
t, q = Tools({"status": "refused", "reason": "over_cap"}), Queue(9)
r = run(m, t, q)
check(r.outcome == "queued" and r.reason == "over_cap" and r.item_id == "9", "over the cap is queued")
check(len(q.items) == 1 and q.items[0]["args"]["customer_id"] == CUST, "one proposal, for the case's customer")

# --- the model closes the case itself ----------------------------------------------------------------------
m = Model(Reply(use(1, "get_order", order_id="ord_1001")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
r = run(m)
check(r.outcome == "refused" and r.reason == "not_eligible", "the model can close a case as not eligible")
m = Model(Reply(use(1, "close_case", outcome="needs_person", reason="missing_details")))
r = run(m)
check(r.outcome == "needs_person" and r.reason == "missing_details" and r.steps == [], "a case may be closed before any lookup")

# --- what the model may not see or do ----------------------------------------------------------------------
m = Model(Reply(use(1, "get_order", order_id="ord_2001")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
r = run(m)
shown = tool_results(m, 1)[0]["content"]
check("no such order for this customer" in shown and "SECRET" not in shown and "540" not in shown, "another customer's order is hidden")
m2 = Model(Reply(use(1, "get_order", order_id="ord_9999")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
run(m2)
check(tool_results(m2, 1)[0]["content"] == tool_results(m, 1)[0]["content"], "a missing order and someone else's look the same")
check(r.steps[0]["tool"] == "get_order", "the lookup still counts as a step")

m = Model(Reply(use(1, "get_account")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
t = Tools()
run(m, t)
check(t.log[0] == ("get_account", CUST), "get_account uses the case's customer")
m = Model(Reply(use(1, "get_account", customer_id="cust_002")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
t = Tools()
run(m, t)
check(t.log == [] and "no arguments" in tool_results(m, 1)[0]["content"], "a customer id given to get_account is refused and nothing runs")

m = Model(Reply(use(1, "get_order", order_id="ord_1\n")), Reply(use(2, "get_order", order_id="ord_1001; drop table")),
          Reply(use(3, "close_case", outcome="refused", reason="not_eligible")))
t = Tools()
r = run(m, t)
check(t.log == [] and r.steps == [], "a bad order id never reaches a tool and is not a step")
m = Model(Reply(use(1, "search_policy", query="")), Reply(use(2, "search_policy", query="x" * 201)),
          Reply(use(3, "close_case", outcome="refused", reason="not_eligible")))
t = Tools()
run(m, t)
check(t.log == [], "an empty or over-long query never reaches a tool")

m = Model(Reply(use(1, "request_refund", order_id="ord_1001", amount="19.00", clause_doc="tos_v3", clause_id="3.3", customer_id="cust_002")),
          Reply(use(2, "close_case", outcome="needs_person", reason="needs_evidence")))
t = Tools(PREVIEW, DONE)
r = run(m, t)
check(t.log == [] and "customer_id" in tool_results(m, 1)[0]["content"], "a refund request that names a customer is rejected, with the field name")
check(r.outcome == "needs_person", "and the model can still close the case")
m = Model(Reply(use(1, "delete_everything")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
run(m)
check("unknown tool" in tool_results(m, 1)[0]["content"], "an unknown tool is refused")
m = Model(Reply(use(1, "close_case", outcome="settled", reason="")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
r = run(m)
check("rejected" in tool_results(m, 1)[0]["content"] and r.outcome == "refused", "close_case cannot settle a case")

# --- the search result is cut ------------------------------------------------------------------------------
m = Model(Reply(use(1, "search_policy", query="refund")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
run(m)
check(len(tool_results(m, 1)[0]["content"]) <= MAX_RESULT_CHARS, "a tool result is cut to the fixed length")

# --- faults end the case with a person ---------------------------------------------------------------------
r = run(Model(RuntimeError("api down for cust_001")))
check(r.outcome == "needs_person" and r.reason == "model_error" and r.error == "RuntimeError", "a model error goes to a person")
check("api down" not in str(r.to_dict()), "the error message is never kept")
r = run(Model(Reply(Block(type="text", text="I will refund it"), stop="end_turn")))
check(r.outcome == "needs_person" and r.reason == "no_decision", "a reply with no tool call is no decision")
r = run(Model(Reply(use(1, "get_order", order_id="ord_1001"), stop="max_tokens")))
check(r.outcome == "needs_person" and r.reason == "model_truncated", "a cut-off reply is not acted on")
t = Tools(fail="get_order")
r = run(Model(Reply(use(1, "get_order", order_id="ord_1001"))), t)
check(r.outcome == "needs_person" and r.reason == "tool_error" and r.error == "TimeoutError", "a read tool that fails goes to a person")
check(r.steps[0]["status"] == "error", "and is recorded as an error step")

# --- the limits --------------------------------------------------------------------------------------------
m = Model(*[Reply(use(i, "get_order", order_id="ord_1001")) for i in range(1, 6)])
r = run(m, max_steps=3)
check(r.outcome == "needs_person" and r.reason == "step_limit" and len(r.steps) == 3, "the fourth tool call is past the step limit")
check(len(m.sent) == 4, "the model is not asked again after the limit")
m = Model(*[Reply(use(i, "get_order", order_id="bad")) for i in range(1, MAX_TURNS + 3)])
r = run(m)
check(r.reason == "turn_limit" and len(m.sent) == MAX_TURNS and r.steps == [], "a model that only sends invalid calls stops at the turn limit")
t = Tools(PREVIEW, DONE)
r = run(Model(Reply(use(1, "request_refund", order_id="ord_1001", amount="19.00", clause_doc="tos_v3", clause_id="3.3"))), t, max_steps=1)
check(r.reason == "step_limit" and t.log == [], "a refund that cannot finish is not started")

# --- several calls in one reply ----------------------------------------------------------------------------
m = Model(Reply(use(1, "close_case", outcome="refused", reason="not_eligible"), use(2, "get_order", order_id="ord_1001")))
t = Tools()
r = run(m, t)
check(r.outcome == "refused" and t.log == [], "a call after the case is closed is ignored")
m = Model(Reply(use(1, "get_order", order_id="ord_1001"), use(2, "get_account")), Reply(use(3, "close_case", outcome="refused", reason="not_eligible")))
t = Tools()
r = run(m, t)
check([x[0] for x in t.log] == ["get_order", "get_account"] and len(tool_results(m, 1)) == 2, "two read calls in one reply both run and both get a result")

# --- thinking blocks are sent back unchanged ---------------------------------------------------------------
think = Block(type="thinking", thinking="hmm", signature="sig")
m = Model(Reply(think, use(1, "get_order", order_id="ord_1001")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible")))
run(m)
sent_back = m.sent[1]["messages"][1]["content"]
check(sent_back[0] == {"type": "thinking", "thinking": "hmm", "signature": "sig"}, "a thinking block goes back as it came")

# --- the caller's mistakes are loud ------------------------------------------------------------------------
try:
    run_billing(MESSAGE, CASE, CUST, "05/11/2026", Tools(), Queue(), create_fn=Model())
    check(False, "a bad date")
except ValueError:
    check(True, "a date that is not ISO is refused")
try:
    run_billing(MESSAGE, "case_x", CUST, "2026-11-05", Tools(), Queue(), create_fn=Model())
    check(False, "a bad case id")
except ValueError:
    check(True, "a case id that is not server-made is refused")
check(billing.MODEL == "claude-haiku-5-5", "the model name is one constant")
check(MESSAGE not in str(r.to_dict()), "the message is not kept in the record")

print(f"BILLING AGENT TESTS: {n} checks passed")
