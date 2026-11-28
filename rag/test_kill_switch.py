"""Offline tests for the kill switch command and migration 017. Run from the rag folder: uv run python test_kill_switch.py"""
import re
from pathlib import Path

import kill_switch as ks

n = 0


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


class Cur:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Conn:
    def __init__(self, login="postgres", enabled=True, row=("on", "initial state", "migration 017", "2026-11-28")):
        self.login, self.enabled, self.row = login, enabled, row
        self.sql, self.committed, self.closed = [], False, False

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        if "current_user" in sql:
            return Cur((self.login,))
        if "writes_enabled" in sql:
            return Cur((self.enabled,))
        if "from ops.system_flags" in sql:
            return Cur(self.row)
        return Cur(None)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def run(argv, conn=None, url="postgresql://owner:SECRET@host/db"):
    conn = conn or Conn()
    lines = []
    code = ks.main(argv, connect=lambda u: conn, env={"REVIEW_OWNER_DATABASE_URL": url} if url else {}, out=lines.append)
    return code, lines, conn


code, lines, conn = run(["status"])
check("status reports ON", lines[0] == "writes: ON" and code == 0)
check("status changes nothing", not conn.committed and not any("insert" in s for s, _ in conn.sql))
check("status closes the connection", conn.closed)
check("status shows who changed it and why", "migration 017" in lines[1] and "initial state" in lines[1])

code, lines, conn = run(["status"], Conn(enabled=False, row=None))
check("no flag row is reported as OFF and fail closed", lines[0] == "writes: OFF" and "fail closed" in lines[1])

code, lines, conn = run(["off", "--by", "Saurabh", "--reason", "drill: model misbehaving"], Conn(enabled=False, row=("off", "r", "Saurabh", "t")))
upsert = [(s, p) for s, p in conn.sql if "insert into ops.system_flags" in s]
check("off writes one upsert with value, reason and name", len(upsert) == 1 and upsert[0][1] == ("off", "drill: model misbehaving", "Saurabh"))
check("off commits and closes", conn.committed and conn.closed)
check("off reads the state back from the database", lines[0] == "writes switched OFF by Saurabh" and lines[1] == "writes: OFF")
check("values are passed as parameters, not pasted into the SQL", "Saurabh" not in upsert[0][0] and "drill" not in upsert[0][0])

code, lines, conn = run(["on", "--by", "Saurabh", "--reason", "drill over"])
check("on writes 'on'", [p for s, p in conn.sql if "insert into ops.system_flags" in s][0][0] == "on")

for bad_args, why in [(["off", "--by", "x"], "missing reason"), (["off", "--reason", "r"], "missing name"),
                      (["off", "--by", "x", "--reason", ""], "empty reason"),
                      (["off", "--by", "x", "--reason", "a" * 201], "long reason"),
                      (["off", "--by", "x", "--reason", "two\nlines"], "newline in reason"),
                      (["off", "--by", "a;drop", "--reason", "r"], "odd characters in the name"),
                      (["off", "--by", "", "--reason", "r"], "empty name")]:
    try:
        run(bad_args)
        failed = False
    except SystemExit:
        failed = True
    check(f"refused: {why}", failed)

made = []
try:
    ks.main(["off", "--by", "x", "--reason", ""], connect=lambda u: made.append(u), env={"REVIEW_OWNER_DATABASE_URL": "u"})
except SystemExit:
    pass
check("bad arguments are refused before any connection is made", made == [])

for argv in (["status"], ["off", "--by", "x", "--reason", "r"]):
    try:
        run(argv, Conn(login="desk_service"))
        refused = False
    except SystemExit as exc:
        refused = "desk_service" in str(exc)
    check(f"the desk_service login is refused ({argv[0]})", refused)
try:
    run(["status"], url="")
    refused = False
except SystemExit as exc:
    refused = "REVIEW_OWNER_DATABASE_URL" in str(exc)
check("no owner URL is refused with a pointer to the variable", refused)
check("the connection string is never printed", "SECRET" not in " ".join(run(["status"])[1]))

# the migration text
sql = (Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "017_write_kill_switch.sql").read_text(encoding="utf-8")
for table in ("refunds", "cancellations", "deletion_requests", "export_requests"):
    check(f"the trigger is on ops.{table}", re.search(rf"create trigger kill_switch before insert or update or delete or truncate on ops\.{table}\s", sql) is not None)
check("the review queue and audit log have no kill switch trigger", "on ops.review_items" not in sql and "on ops.audit_log" not in sql)
check("the triggers are statement level", sql.count("for each statement execute function ops.block_writes_when_off()") == 4)
check("a missing row means off", "coalesce((select value = 'on' from ops.system_flags where name = 'writes'), false)" in sql)
check("the refusal uses sqlstate 55000", "errcode = '55000'" in sql)
check("writes start on, and only when no row exists", "values ('writes', 'on'" in sql and "on conflict (name) do nothing" in sql)
check("the service logins lose all access to the flag", "revoke all on ops.system_flags, ops.system_flag_history from public" in sql and "'ops_writer'" in sql and "'desk_service'" in sql)
check("the flag can only be 'on' or 'off'", "check (value in ('on', 'off'))" in sql)

print(f"\n{n} checks passed")
