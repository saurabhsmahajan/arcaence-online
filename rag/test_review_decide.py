"""Offline tests for the decide script's checks. The database rules themselves are proved by test_review_queue.py and prove_human_gate.py."""
import review_decide as rd

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


GOOD = "3f2a9c1e-5b7d-4e8a-9c3b-1a2b3c4d5e6f"
check(rd.check_decision(GOOD, "approve", "saurabh", "ok") == [], "a good decision has no problems")
check(rd.check_decision(GOOD, "reject", "saurabh", None) == [], "a rejection with no note is fine")
for bad_id in ("", "x", GOOD.upper(), GOOD + "0", "'; drop table ops.review_items; --", None, 5):
    check(rd.check_decision(bad_id, "approve", "me", None) == ["item_id"], f"a bad item id is refused: {str(bad_id)[:20]!r}")
for bad_action in ("executed", "APPROVE", "approved", "", None):
    check(rd.check_decision(GOOD, bad_action, "me", None) == ["action"], f"only approve or reject: {bad_action!r}")
for bad_by in ("", "   ", None, "x" * 61, 5):
    check(rd.check_decision(GOOD, "approve", bad_by, None) == ["by"], f"a decision needs a name: {str(bad_by)[:10]!r}")
check(rd.check_decision(GOOD, "approve", "me", "x" * 301) == ["note"], "a long note is refused")
check(rd.check_decision("x", "run", "", 5) == ["item_id", "action", "by", "note"], "every problem is reported")


class Cur:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Conn:
    def __init__(self, row=None):
        self.row, self.sql = row, []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return Cur(self.row)

    def close(self):
        pass


c = Conn(("3f2a9c1e-5b7d-4e8a-9c3b-1a2b3c4d5e6f", "approved", "saurabh", "2026-11-27"))
out = rd.decide(c, GOOD, "approve", "  saurabh ", "  fine  ")
sql, params = c.sql[0]
check("update ops.review_items" in sql and "kind = 'proposed_action'" in sql, "it updates only proposed actions")
check(params == ("approved", "saurabh", "fine", GOOD), "it sends the status word, the trimmed name and note, and the id as parameters")
check("delete" not in sql.lower() and "refund" not in sql.lower(), "the statement does nothing but record the decision")
check(out["status"] == "approved" and out["decided_by"] == "saurabh", "it returns what was recorded")
check(rd.decide(Conn(("i", "rejected", "me", "d")), GOOD, "reject", "me")["status"] == "rejected", "a rejection records rejected")
c = Conn(("i", "approved", "me", "d"))
rd.decide(c, GOOD, "approve", "me", "")
check(c.sql[0][1][2] is None, "an empty note is stored as no note")

for args in (("x", "approve", "me"), (GOOD, "run", "me"), (GOOD, "approve", "")):
    c = Conn()
    try:
        rd.decide(c, *args)
        check(False, "a bad decision must not reach the database")
    except ValueError:
        check(c.sql == [], f"a bad decision never reaches the database: {args}")
try:
    rd.decide(Conn(None), GOOD, "approve", "me")
    check(False, "no such item")
except LookupError:
    check(True, "an item that is not a proposed action is not found")

# the owner connection refuses the desk login and a missing setting
try:
    rd.owner_connection("")
    check(False, "no url")
except SystemExit:
    check(True, "no owner URL is refused")


class Login(Conn):
    def __init__(self, user):
        super().__init__((user,))
        self.closed = False

    def close(self):
        self.closed = True


desk = Login("desk_service")
try:
    rd.owner_connection("x", connect=lambda url: desk)
    check(False, "desk login")
except SystemExit:
    check(desk.closed, "the desk_service login is refused and closed")
owner = Login("postgres")
check(rd.owner_connection("x", connect=lambda url: owner) is owner, "another login is accepted")

print(f"REVIEW DECIDE TESTS: {n} checks passed")
