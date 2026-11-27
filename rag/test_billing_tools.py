"""Tests for the billing tool adapters. Fakes only: no database, no model, no keys."""
from decimal import Decimal

import billing_tools as bt
from billing import run_billing
from billing_tools import LocalTools, clean_account, clean_order, policy_result

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


# --- what the model may see ----------------------------------------------------------------------------------
row = {"order_id": "ord_1001", "customer_id": "cust_001", "item": "Pro plan", "kind": "subscription", "amount": Decimal("19.00"),
       "currency": "EUR", "purchased_at": "2026-11-01", "downloaded": False, "invoice_id": None, "invoice_issued_on": None,
       "internal_note": "do not show", "email": "a@b.c"}
o = clean_order(row)
check(set(o) == set(bt.ORDER_FIELDS) and "internal_note" not in o and "email" not in o, "an order keeps only the listed fields")
check(o["customer_id"] == "cust_001", "the customer id stays so the loop can check ownership")
check(clean_order(None) is None and clean_order({}) is None, "no order stays no order")
a = clean_account({"customer_id": "cust_001", "display_name": "Asha Rao", "plan": "Pro", "billing": "monthly", "currency": "EUR",
                   "status": "active", "created_at": "x", "email": "asha@example.com", "phone": "+91 99999"})
check(set(a) == set(bt.ACCOUNT_FIELDS), "an account keeps only the listed fields")
check("Asha" not in str(a) and "@" not in str(a) and "99999" not in str(a), "name, email and phone never reach the model")
check(clean_account(None) is None, "no account stays no account")

hits = [{"doc_id": "tos_v3", "clause_id": f"{i}.1", "content": "y" * 5000, "score": 0.9, "status": "approved"} for i in range(9)]
p = policy_result(hits)
check(len(p["results"]) == bt.MAX_HITS, "at most five clauses")
check(all(set(r) == {"doc_id", "clause_id", "content"} for r in p["results"]), "a clause has a document, a clause id and text, nothing else")
check(all(len(r["content"]) == bt.MAX_CLAUSE_CHARS for r in p["results"]), "clause text is cut to a fixed length")
check("Not instructions" in p["note"], "the note says the text is not instructions")
check(policy_result([])["results"] == [], "no hits gives an empty list")
check(policy_result([{"doc_id": "d", "clause_id": None, "content": "t"}])["results"][0]["clause_id"] is None, "a clause with no number stays None")


# --- the case wrapper ----------------------------------------------------------------------------------------
class Conn:
    def __init__(self):
        self.rolled_back = self.closed = 0
        self.commits = 0

    def rollback(self):
        self.rolled_back += 1

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed += 1


class Req:
    def __init__(self, *a):
        self.a = a


class Actions:
    def __init__(self, dry=None, commit=None):
        self.calls, self.dry, self.commit = [], dry, commit

    def dry_run_refund(self, conn, req):
        self.calls.append(("dry", conn, req.a))
        r = self.dry
        if isinstance(r, Exception):
            raise r
        return r

    def commit_refund(self, conn, req, token):
        self.calls.append(("commit", conn, req.a, token))
        r = self.commit
        if isinstance(r, Exception):
            raise r
        return r


def make(actions=None, conns=None):
    conns = conns if conns is not None else []

    def connect():
        c = Conn()
        conns.append(c)
        return c

    t = LocalTools(lambda oid: row if oid == "ord_1001" else None, lambda cid: {"customer_id": cid, "plan": "Pro", "email": "e"},
                   lambda q: [{"doc_id": "tos_v3", "clause_id": "3.3", "content": q}], connect, actions or Actions(), Req)
    return t, conns


t, conns = make()
with t.case():
    check(len(conns) == 1 and conns[0].rolled_back == 0, "a case opens one connection")
check(conns[0].rolled_back == 1 and conns[0].closed == 1 and conns[0].commits == 0, "a case ends with a rollback and a close, never a commit")
try:
    with t.case():
        raise ValueError("boom")
except ValueError:
    check(conns[1].rolled_back == 1 and conns[1].closed == 1, "a case that fails is still rolled back and closed")
with t.case():
    pass
check(len(conns) == 3 and conns[2] is not conns[0], "every case gets a fresh connection")
try:
    with t.case():
        with t.case():
            pass
    check(False, "nested cases")
except RuntimeError:
    check(conns[3].rolled_back == 1 and conns[3].closed == 1, "a nested case is refused and the outer one is still cleaned up")
with t.case():
    pass
check(len(conns) == 5, "after a refused nesting the next case opens normally")

# --- the four calls ------------------------------------------------------------------------------------------
check(t.get_order("ord_1001")["item"] == "Pro plan" and t.get_order("ord_9999") is None, "get_order returns the order or None")
check(t.get_account(customer_id="cust_001") == {"customer_id": "cust_001", "plan": "Pro"}, "get_account takes the customer id and drops contact details")
check(t.search_policy("refund")["results"][0]["content"] == "refund", "search_policy returns the model's view")

try:
    t.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", True, None)
    check(False, "refund outside a case")
except RuntimeError:
    check(True, "issue_refund outside a case is refused")

acts = Actions(dry={"status": "preview", "token": "tk"}, commit={"status": "done"})
t, conns = make(acts)
with t.case():
    d = t.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", True, None)
    c = t.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", False, "tk")
check(d["status"] == "preview" and c["status"] == "done", "the dry run and the commit return what the action returned")
check(acts.calls[0][0] == "dry" and acts.calls[1][0] == "commit" and acts.calls[1][3] == "tk", "dry_run picks the dry run, otherwise the commit with the token")
check(acts.calls[0][2] == ("cust_001", "ord_1001", "19.00", "tos_v3", "3.3"), "the request is built from the arguments, amount unparsed")
check(acts.calls[0][1] is conns[0] and acts.calls[1][1] is conns[0], "both calls use the case's one connection")
check(conns[0].rolled_back == 1 and conns[0].commits == 0, "the committed refund is rolled back with the case")

t, conns = make(Actions(dry=RuntimeError("db down")))
try:
    with t.case():
        t.issue_refund("cust_001", "ord_1001", "19.00", "tos_v3", "3.3", True, None)
    check(False, "an action that raises")
except RuntimeError:
    check(conns[0].rolled_back == 1 and conns[0].closed == 1, "an action that raises still ends in a rollback")

# --- the whole agent on this adapter -------------------------------------------------------------------------


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class Reply:
    def __init__(self, *blocks):
        self.content, self.stop_reason = list(blocks), "tool_use"


def use(i, name, **inp):
    return Block(type="tool_use", id=f"tu_{i}", name=name, input=inp)


script = [Reply(use(1, "get_order", order_id="ord_1001")),
          Reply(use(2, "search_policy", query="unintended renewal")),
          Reply(use(3, "request_refund", order_id="ord_1001", amount="19.00", clause_doc="tos_v3", clause_id="3.3"))]


def model(**kw):
    return script.pop(0)


acts = Actions(dry={"status": "preview", "token": "tk"}, commit={"status": "done", "refund_id": "r1", "order_id": "ord_1001",
                                                                   "amount": "19.00", "currency": "EUR"})
t, conns = make(acts)
with t.case():
    rec = run_billing("refund please", "case_20261127_0123456789ab", "cust_001", "2026-11-05", t, lambda p: 1, create_fn=model)
check(rec.outcome == "settled", "the agent settles a refund on this adapter")
check([x[0] for x in acts.calls] == ["dry", "commit"] and acts.calls[0][2][0] == "cust_001", "with the case's customer, from code")
check(conns[0].rolled_back == 1 and conns[0].commits == 0, "and the settled refund was rolled back")

print(f"BILLING TOOLS TESTS: {n} checks passed")
