"""Tests for the privacy agent loop. A scripted fake model and fake tools: no real model, no database, no keys."""
import copy
import json

import privacy
from privacy import MAX_RESULT_CHARS, MAX_TURNS, SYSTEM, TOOLS, run_privacy
from privacy_logic import ACTION_TOOLS, AGENT_CLOSES, MODEL_TOOLS

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


CASE = "case_20261127_0123456789ab"
CUST = "cust_001"
RID = "1db066c7-fd3a-4560-8387-8ff421aefed0"
INV = {"orders": 2, "invoices": 1}
EXPORT, DELETE, CANCEL = "request_data_export", "request_account_deletion", "cancel_deletion_request"
MESSAGE = "Please delete my account. My email is secret.person@example.com"


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


class Tools:
    def __init__(self, fail=False, **results):
        self.results, self.fail, self.log = results, fail, []

    def _call(self, name, customer_id):
        self.log.append((name, customer_id))
        if self.fail:
            raise TimeoutError("db slow: password=hunter2")
        return self.results[name]

    def request_data_export(self, customer_id):
        return self._call(EXPORT, customer_id)

    def request_account_deletion(self, customer_id):
        return self._call(DELETE, customer_id)

    def cancel_deletion_request(self, customer_id):
        return self._call(CANCEL, customer_id)


OK_DELETE = {"status": "requested", "kind": "deletion", "request_id": RID, "next_step": "text"}
OK_EXPORT = {"status": "requested", "kind": "export", "request_id": RID, "inventory": INV, "next_step": "text"}
OK_CANCEL = {"status": "cancelled", "kind": "deletion", "request_id": RID, "next_step": "text"}


def run(model, tools, message=MESSAGE, **kw):
    return run_privacy(message, CASE, CUST, tools, create_fn=model, **kw)


# the tool list the model is given
names = [t["name"] for t in TOOLS]
check(sorted(names) == sorted(MODEL_TOOLS), "the model is offered exactly the allowed tools")
check(all(t["input_schema"].get("additionalProperties") is False for t in TOOLS), "every schema rejects extra arguments")
check(all(not t["input_schema"]["properties"] for t in TOOLS if t["name"] in ACTION_TOOLS), "a privacy tool takes no arguments")
check("customer_id" not in json.dumps(TOOLS), "no tool has a customer id for the model to fill in")
check(set(next(t for t in TOOLS if t["name"] == "close_case")["input_schema"]["properties"]["outcome"]["enum"]) == set(AGENT_CLOSES),
      "close_case offers only the agent's outcomes")
check("requested" not in json.dumps(next(t for t in TOOLS if t["name"] == "close_case")), "the model cannot close as requested")
check("cust_" not in SYSTEM and "@" not in SYSTEM, "the prompt holds no customer id or address")

# good paths
m, t = Model(Reply(use(1, DELETE))), Tools(**{DELETE: OK_DELETE})
r = run(m, t)
check(r.outcome == "requested" and r.kind == "deletion" and r.request_id == RID, "a deletion request is opened")
check(t.log == [(DELETE, CUST)], "the tool was called once, with the case's customer id")
check(len(m.sent) == 1 and m.sent[0]["model"] == privacy.MODEL and m.sent[0]["tools"] == TOOLS, "one model call with the fixed tools")
check(m.sent[0]["system"] == SYSTEM and CUST not in m.sent[0]["system"], "the system prompt is fixed and holds no customer")
check(m.sent[0]["messages"] == [{"role": "user", "content": f"Customer message: {MESSAGE}"}], "the message goes in as user data")
m, t = Model(Reply(use(1, EXPORT))), Tools(**{EXPORT: OK_EXPORT})
r = run(m, t)
check(r.outcome == "requested" and r.kind == "export" and r.inventory == INV, "an export request keeps its counts")
m, t = Model(Reply(use(1, CANCEL))), Tools(**{CANCEL: OK_CANCEL})
r = run(m, t)
check(r.outcome == "cancelled", "a cancel")
m, t = Model(Reply(use(1, DELETE))), Tools(**{DELETE: {"status": "refused", "reason": "request_already_open"}})
r = run(m, t)
check(r.outcome == "refused" and r.reason == "request_already_open", "the tool's refusal ends the case")

# the model closes the case itself
m, t = Model(Reply(use(1, "close_case", outcome="needs_person", reason="unclear_request"))), Tools()
r = run(m, t)
check(r.outcome == "needs_person" and r.reason == "unclear_request" and t.log == [] and r.steps == [], "closed with no tool")
m, t = Model(Reply(use(1, "close_case", outcome="refused", reason="not_eligible"))), Tools()
check(run(m, t).outcome == "refused", "closed as not_eligible")

# the model asks for what it may not
m, t = Model(Reply(use(1, DELETE, customer_id="cust_002")), Reply(use(2, DELETE))), Tools(**{DELETE: OK_DELETE})
r = run(m, t)
check(r.outcome == "requested" and t.log == [(DELETE, CUST)], "a customer id from the model is rejected, then it asks properly")
second = json.loads(m.sent[1]["messages"][-1]["content"][0]["content"])
check(second == {"status": "rejected", "problems": ["customer_id"]}, "the model is told which argument was refused")
check("cust_002" not in json.dumps(m.sent[1]["messages"][-1]), "the rejected id is not echoed back")
m, t = Model(Reply(use(1, "issue_refund", order_id="ord_1001", amount="19.00")), Reply(use(2, "close_case", outcome="needs_person", reason="not_supported"))), Tools()
r = run(m, t)
check(r.outcome == "needs_person" and t.log == [], "a billing tool is unknown here and nothing ran")
check(json.loads(m.sent[1]["messages"][-1]["content"][0]["content"]) == {"error": "unknown tool"}, "the model hears that it is unknown")
m, t = Model(Reply(use(1, "close_case", outcome="requested", reason="")), Reply(use(2, "close_case", outcome="refused", reason="not_eligible"))), Tools()
r = run(m, t)
check(r.outcome == "refused" and t.log == [], "close_case cannot claim requested, and the model may try again")
check(json.loads(m.sent[1]["messages"][-1]["content"][0]["content"])["problems"] == ["outcome"], "the model hears which field was wrong")
m, t = Model(Reply(Block(type="tool_use", id="x", name=DELETE, input="cust_001")), Reply(use(2, DELETE))), Tools(**{DELETE: OK_DELETE})
check(run(m, t).outcome == "requested", "arguments that are not an object are refused, not run")

# one action per case
m, t = Model(Reply(use(1, EXPORT), use(2, DELETE))), Tools(**{EXPORT: OK_EXPORT, DELETE: OK_DELETE})
r = run(m, t)
check(r.outcome == "requested" and r.kind == "export" and t.log == [(EXPORT, CUST)], "only the first tool in a turn runs")
check(len(m.sent) == 1, "the case ended in one model call")

# faults
m, t = Model(RuntimeError("secret key sk-123 leaked")), Tools()
r = run(m, t)
check(r.outcome == "needs_person" and r.reason == "model_error" and r.error == "RuntimeError", "a model fault ends as model_error")
check("sk-123" not in str(r.to_dict()), "the error message is never kept")
m, t = Model(Reply(use(1, DELETE), stop="max_tokens")), Tools(**{DELETE: OK_DELETE})
r = run(m, t)
check(r.reason == "model_truncated" and t.log == [], "a cut-off reply does nothing")
m, t = Model(Reply(Block(type="text", text="Sure, I deleted it."), stop="end_turn")), Tools(**{DELETE: OK_DELETE})
r = run(m, t)
check(r.reason == "no_decision" and t.log == [], "free text is not a decision")
m, t = Model(*[Reply(use(i, "close_case", outcome="requested", reason="")) for i in range(MAX_TURNS + 3)]), Tools()
r = run(m, t)
check(r.outcome == "needs_person" and r.reason == "turn_limit" and len(m.sent) == MAX_TURNS, "a model that only sends bad calls stops")
m, t = Model(Reply(use(1, DELETE))), Tools(fail=True)
r = run(m, t)
check(r.outcome == "needs_person" and r.reason == "tool_error" and r.error == "TimeoutError" and "hunter2" not in str(r.to_dict()),
      "a tool fault ends as tool_error and keeps only the class name")
m, t = Model(Reply(use(1, DELETE))), Tools(**{DELETE: {"status": "requested", "kind": "export", "request_id": RID}})
check(run(m, t).reason == "unexpected_result", "a result nobody planned for is needs_person")
m, t = Model(Reply(use(1, DELETE))), Tools(**{DELETE: OK_DELETE})
check(run(m, t, max_steps=1).outcome == "requested", "the default limit allows the one action")

# what the model is shown and what is kept
check(MAX_RESULT_CHARS <= 2000 and privacy._show({"a": "x" * 5000}) .__len__() == MAX_RESULT_CHARS, "a tool result is cut to a fixed length")
m, t = Model(Reply(use(1, DELETE))), Tools(**{DELETE: OK_DELETE})
r = run(m, t)
check(MESSAGE not in str(r.to_dict()) and "secret.person" not in str(r.to_dict()), "the message is not in the record")
check(r.trace_fields() == {"privacy_outcome": "requested", "privacy_reason": "", "privacy_kind": "deletion",
                           "privacy_steps": 1, "privacy_error": ""}, "the trace fields are labels and counts")
try:
    run_privacy(MESSAGE, "case_x", CUST, Tools(), create_fn=Model())
    check(False, "a bad case id must raise")
except ValueError:
    check(True, "a bad case id is a bug in the caller and raises")
try:
    run_privacy(MESSAGE, CASE, "cust_1", Tools(), create_fn=Model())
    check(False, "a bad customer id must raise")
except ValueError:
    check(True, "a bad customer id is a bug in the caller and raises")

print(f"PRIVACY AGENT TESTS: {n} checks passed")
