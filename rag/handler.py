"""handle_message: one customer message in, one reply out, with the side effects kept out of the desk.

desk_answer() stays a function of the message alone: no database writes, so the evaluation and CI
can run it with a read-only login. This handler is the layer that acts on the handoff flag.

If a message needs a person, it is added to the review queue. If the queue cannot be written, a
reply that says "marking it for review" would be untrue, so the escalate reply is replaced by a
fixed one that promises nothing, and the result says the item was not queued.
"""
import os

from desk_logic import QUEUE_FAILED_REPLY


def _default_enqueue(result):
    import psycopg
    from review import enqueue_answer

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:  # commits when the block ends
        return enqueue_answer(conn, result)


def handle_message(question: str, answer_fn=None, enqueue_fn=None) -> dict:
    if answer_fn is None:
        from desk import desk_answer as answer_fn
    enqueue_fn = enqueue_fn or _default_enqueue

    result = answer_fn(question)
    result["review"] = {"needed": result["handoff"]["needed"], "queued": False, "item_id": None, "error": ""}
    if not result["handoff"]["needed"]:
        return result
    try:
        result["review"]["item_id"] = str(enqueue_fn(result))
        result["review"]["queued"] = True
    except Exception as exc:  # the class name only: a message could carry connection details
        result["review"]["error"] = type(exc).__name__
        if result["behavior"] == "escalate":
            result["answer"] = QUEUE_FAILED_REPLY
    return result
