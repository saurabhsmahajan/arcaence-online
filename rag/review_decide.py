"""A person decides a queued proposed action. This is the human side of the gate.

Connects as the database owner through the environment variable REVIEW_OWNER_DATABASE_URL, which you set in your own
shell and never put in a file, in git or in the service. The desk service cannot do this: its login can add and read
items but has no UPDATE (migration 016), and a database trigger lets a decision happen once and only change the decision.

Approving records a person's decision and NOTHING ELSE. No refund is made here or anywhere because of it (ADR-056).

  uv run python review_decide.py list
  uv run python review_decide.py approve <item-id> --by <your name> --note "why"
  uv run python review_decide.py reject  <item-id> --by <your name> --note "why"
"""
import argparse
import json
import os
import re
import sys

ITEM_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DECISIONS = {"approve": "approved", "reject": "rejected"}
MAX_NOTE = 300
MAX_BY = 60
DESK_LOGIN = "desk_service"


def check_decision(item_id, action, by, note) -> list[str]:
    """Everything wrong with a decision, as field names. Empty means it may go to the database."""
    problems = []
    if not (isinstance(item_id, str) and ITEM_ID.fullmatch(item_id)):
        problems.append("item_id")
    if action not in DECISIONS:
        problems.append("action")
    if not (isinstance(by, str) and by.strip() and len(by) <= MAX_BY):
        problems.append("by")
    if note is not None and not (isinstance(note, str) and len(note) <= MAX_NOTE):
        problems.append("note")
    return problems


def decide(conn, item_id, action, by, note=None) -> dict:
    """Record one decision on a proposed action. The caller owns the transaction. Raises ValueError for a bad request and
    LookupError if there is no such proposed action; the database refuses a second decision."""
    problems = check_decision(item_id, action, by, note)
    if problems:
        raise ValueError("bad decision: " + ", ".join(problems))
    row = conn.execute(
        "update ops.review_items set status = %s, decided_by = %s, decision_note = %s "
        "where item_id = %s and kind = 'proposed_action' returning item_id, status, decided_by, decided_at",
        (DECISIONS[action], by.strip(), (note or "").strip() or None, item_id)).fetchone()
    if row is None:
        raise LookupError("no such proposed action")
    return {"item_id": str(row[0]), "status": row[1], "decided_by": row[2], "decided_at": row[3]}


def list_open(conn) -> list[dict]:
    rows = conn.execute("select item_id, case_id, created_at, summary, proposed from ops.review_items "
                        "where kind = 'proposed_action' and status = 'open' order by created_at").fetchall()
    return [{"item_id": str(r[0]), "case_id": r[1], "created_at": r[2], "summary": r[3], "proposed": r[4]} for r in rows]


def owner_connection(url, connect=None):
    """A connection that is NOT the desk login: the desk service must never be the one that decides."""
    if not url:
        raise SystemExit("Set REVIEW_OWNER_DATABASE_URL in your own shell first. Never paste it anywhere.")
    import psycopg

    conn = (connect or psycopg.connect)(url)
    login = conn.execute("select current_user").fetchone()[0]
    if login == DESK_LOGIN:
        conn.close()
        raise SystemExit("That is the desk_service login. A person decides as the owner, never as the service.")
    return conn


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in DECISIONS:
        p = sub.add_parser(name)
        p.add_argument("item_id")
        p.add_argument("--by", required=True)
        p.add_argument("--note")
    args = ap.parse_args(argv)
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    with owner_connection(os.environ.get("REVIEW_OWNER_DATABASE_URL")) as conn:   # commits when the block ends
        if args.cmd == "list":
            items = list_open(conn)
            for it in items:
                print(f"{it['item_id']}  {it['case_id']}  {it['created_at']:%Y-%m-%d %H:%M}\n    {it['summary']}\n    {json.dumps(it['proposed'])}")
            print(f"{len(items)} open proposed action(s)")
        else:
            try:
                out = decide(conn, args.item_id, args.cmd, args.by, args.note)
            except (ValueError, LookupError) as exc:
                sys.exit(str(exc))
            print(f"{out['status']}: {out['item_id']} by {out['decided_by']}. Nothing was executed.")


if __name__ == "__main__":
    main()
