"""The write kill switch: a person turns database writes off and on, with a reason that is kept.

Connects as the database owner through REVIEW_OWNER_DATABASE_URL, set in your own shell and never put in a
file, in git or in the service. The desk_service login is refused, as in review_decide.py.

While the switch is off the database refuses every change to refunds, cancellations, deletion requests and
export requests, whatever code tries it. Reads, dry runs, the audit log and the review queue keep working.
It fails closed: if the flag row is missing, writes are off. See migration 017.

  uv run python kill_switch.py status
  uv run python kill_switch.py off --by <your name> --reason "why"
  uv run python kill_switch.py on  --by <your name> --reason "why"
"""
import argparse
import os
import re
import sys

from review_decide import owner_connection

BY = re.compile(r"[A-Za-z0-9 ._@-]{1,60}")
MAX_REASON = 200

UPSERT = (
    "insert into ops.system_flags (name, value, reason, changed_by, changed_at) values ('writes', %s, %s, %s, now()) "
    "on conflict (name) do update set value = excluded.value, reason = excluded.reason, "
    "changed_by = excluded.changed_by, changed_at = now()"
)


def read_state(conn) -> dict:
    """The flag as the database enforces it: enabled is what the triggers see, row is what is stored."""
    enabled = bool(conn.execute("select ops.writes_enabled()").fetchone()[0])
    row = conn.execute("select value, reason, changed_by, changed_at from ops.system_flags where name = 'writes'").fetchone()
    return {"enabled": enabled, "row": row}


def describe(state: dict) -> list[str]:
    lines = [f"writes: {'ON' if state['enabled'] else 'OFF'}"]
    if state["row"] is None:
        lines.append("no flag row: writes are OFF (fail closed). Run 'on' to switch them back on.")
    else:
        value, reason, by, at = state["row"]
        lines.append(f"last change: {value} by {by} at {at}: {reason or '(no reason)'}")
    return lines


def valid_by(value: str) -> str:
    if not BY.fullmatch(value or ""):
        raise SystemExit("--by must be 1 to 60 letters, digits, spaces or . _ @ -")
    return value.strip()


def valid_reason(value: str) -> str:
    text = (value or "").strip()
    if not text or len(text) > MAX_REASON or any(ord(c) < 32 for c in text):
        raise SystemExit(f"--reason is required: one line, at most {MAX_REASON} characters")
    return text


def main(argv=None, connect=None, env=None, out=print) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for name in ("on", "off"):
        p = sub.add_parser(name)
        p.add_argument("--by", required=True)
        p.add_argument("--reason", required=True)
    args = ap.parse_args(argv)

    env = os.environ if env is None else env
    # check the arguments before connecting: a bad flag should not cost a connection
    if args.cmd != "status":
        by, reason = valid_by(args.by), valid_reason(args.reason)
    conn = owner_connection(env.get("REVIEW_OWNER_DATABASE_URL"), connect)
    try:
        if args.cmd != "status":
            conn.execute(UPSERT, (args.cmd, reason, by))
            conn.commit()
            out(f"writes switched {args.cmd.upper()} by {by}")
        for line in describe(read_state(conn)):
            out(line)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
