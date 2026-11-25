"""Adds items to the review queue (ops.review_items). The desk service uses the desk_service login,
which can add and read items and can never decide one."""
import json


def enqueue_answer(conn, result: dict):
    """Add an answer item for a desk result that needs a person. Returns the item id.

    One answer item per case: if this case is already queued the existing id is returned, so a retry
    cannot fill the queue with copies. The caller owns the transaction (commit or roll back).
    """
    handoff = result["handoff"]
    if not handoff["needed"]:
        raise ValueError("this result does not need a review")
    row = conn.execute(
        "insert into ops.review_items (case_id, kind, reason, question, summary) "
        "values (%s, 'answer', %s, %s, %s) "
        "on conflict (case_id) where kind = 'answer' do nothing returning item_id",
        (result["case_id"], handoff["reason"], result["question"], result["answer"]),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "select item_id from ops.review_items where case_id = %s and kind = 'answer'",
            (result["case_id"],),
        ).fetchone()
    return row[0]


def enqueue_action(conn, case_id: str, question: str, summary: str, tool: str, args: dict):
    """Add a proposed action. It records what an agent wants to do. It never runs it."""
    row = conn.execute(
        "insert into ops.review_items (case_id, kind, reason, question, summary, proposed) "
        "values (%s, 'proposed_action', 'proposed_action', %s, %s, %s) returning item_id",
        (case_id, question, summary, json.dumps({"tool": tool, "args": args})),
    ).fetchone()
    return row[0]
