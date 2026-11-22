"""Audit module checks. Run: uv run python test_audit.py   (add --offline to skip the database round trip)"""
import sys
from decimal import Decimal

import audit
import config
import db_write


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


def refused(**kw):
    try:
        audit.log(FakeConn(), **kw)
    except audit.AuditError:
        return True
    return False


fake = FakeConn()
audit.log(fake, tool="issue_refund", mode="commit", outcome="allowed", customer_id="cust_001",
          order_id="ord_1001", amount="19.00", currency="EUR", clause_id="2.2",
          args={"customer_id": "cust_001", "amount": "19.00", "clause_id": "2.2"})
sql, params = fake.calls[0]
assert params[0] == config.ROLE and params[1] == "issue_refund" and params[3] == "allowed"
assert params[7] == Decimal("19.00")
print("PASS  a valid allowed row is built with the launch role and a decimal amount")

assert refused(tool="issue_refund", mode="commit", outcome="refused")
print("PASS  a refusal with no reason code is rejected")

assert refused(tool="issue_refund", mode="commit", outcome="refused", reason="because I said so")
print("PASS  a free-text reason is rejected")

assert refused(tool="issue_refund", mode="commit", outcome="refused", reason="over_cap", args={"email": "a@b.c"})
print("PASS  an argument field outside the allowed list is rejected")

assert refused(tool="issue_refund", mode="launch", outcome="allowed")
assert refused(tool="issue_refund", mode="commit", outcome="maybe")
print("PASS  an unknown mode or outcome is rejected")

ok = FakeConn()
audit.log(ok, tool="issue_refund", mode="dry_run", outcome="refused", reason="no_clause")
assert ok.calls
print("PASS  a refusal with a known reason code is accepted")

if "--offline" in sys.argv:
    print("skipped: database round trip (--offline)")
    sys.exit(0)

with db_write.connect() as conn:
    audit.log(conn, tool="test_audit", mode="dry_run", outcome="refused", reason="over_cap",
              customer_id="cust_001", order_id="ord_1001", amount="999.00", currency="EUR")
    row = conn.execute(
        "select server_role, tool, outcome, reason, amount from ops.audit_log "
        "where tool = 'test_audit' order by audit_id desc limit 1"
    ).fetchone()
    assert row == (config.ROLE, "test_audit", "refused", "over_cap", Decimal("999.00")), row
    conn.rollback()
print("PASS  the row is written to ops.audit_log (then rolled back, nothing kept)")

with db_write.connect() as conn:
    left = conn.execute("select count(*) from ops.audit_log where tool = 'test_audit'").fetchone()[0]
assert left == 0, left
print("PASS  the rolled-back row is gone")
