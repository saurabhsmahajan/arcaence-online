"""Failure handling around the desk answer: every fault ends in a fixed message, never in a made-up answer.

The desk answer calls a classifier model, the database and an answer model. Any of them can fail or
hang. This wrapper gives the whole answer a deadline and turns every fault into the same closed result:
a refusal with a fixed sentence written here and a hand-off flag. The words of an exception are never
copied into the reply, because they can carry connection strings or text a third party controls.

No model, no database and no network in this file, so it tests offline.
"""
import concurrent.futures
import os

from case import new_case_id

DEFAULT_DEADLINE_S = 60.0

UNAVAILABLE_REPLY = (
    "I'm sorry, I can't answer this just now because part of our system is not responding, "
    "and I don't want to guess. Please try again in a few minutes, or contact the Help Centre "
    "so a person can look at it."
)
NO_SOURCES_REPLY = (
    "I can't find anything about this in the official documents, so I won't guess. "
    "The Help Centre can help with this."
)
UNVERIFIED_REPLY = (
    "I could not check my answer against the official documents, so I won't give one. "
    "Please contact the Help Centre so a person can look at it."
)

# the closed set of reasons this wrapper can give
REASONS = ("model_error", "retrieval_error", "timeout", "unexpected_error")

_MODEL_ROOTS = {"anthropic", "httpx", "httpcore"}
_DB_ROOTS = {"psycopg", "psycopg_pool"}

# the keys the handler and the trace read from a desk result
REQUIRED_KEYS = ("case_id", "question", "mode", "label", "behavior", "answer", "citations",
                 "sources", "route", "refused", "refusal_reason", "attempts", "problems", "handoff")


def deadline_seconds(value=None) -> float:
    """The deadline in seconds: the argument, else DESK_DEADLINE_S, else the default. Bad values use the default."""
    raw = value if value is not None else os.environ.get("DESK_DEADLINE_S")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_DEADLINE_S
    return seconds if seconds > 0 else DEFAULT_DEADLINE_S


def fault_reason(exc: BaseException) -> str:
    """A reason from the kind of exception only. The message is never read."""
    root = type(exc).__module__.split(".")[0]
    if root in _MODEL_ROOTS:
        return "model_error"
    if root in _DB_ROOTS:
        return "retrieval_error"
    return "unexpected_error"


def run_with_deadline(fn, seconds: float, *args):
    """Run fn(*args) and give up waiting after `seconds`. The abandoned call is left to finish alone."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn, *args)
    try:
        return future.result(timeout=seconds)
    finally:
        pool.shutdown(wait=False)


def fault_result(question: str, reason: str) -> dict:
    """The one result shape for every fault: a refusal, a fixed sentence and a hand-off."""
    why = f"unavailable_{reason}"
    return {
        "case_id": new_case_id(), "question": question, "mode": "desk", "label": "unknown",
        "classifier_confidence": 0.0, "classifier_note": "", "behavior": "refuse",
        "answer": UNAVAILABLE_REPLY, "citations": [], "sources": [], "route": "none",
        "refused": True, "refusal_reason": why, "attempts": 0, "problems": [],
        "handoff": {"needed": True, "reason": why},
    }


def well_formed(result) -> bool:
    return (isinstance(result, dict) and all(k in result for k in REQUIRED_KEYS)
            and isinstance(result["handoff"], dict) and "needed" in result["handoff"])


def safe_desk_answer(question: str, desk_fn=None, deadline_s=None) -> dict:
    """desk_answer with a deadline. Never raises; a fault comes back as fault_result."""
    if desk_fn is None:
        from desk import desk_answer as desk_fn
    try:
        result = run_with_deadline(desk_fn, deadline_seconds(deadline_s), question)
    except concurrent.futures.TimeoutError:
        return fault_result(question, "timeout")
    except Exception as exc:  # the kind only: the message can hold connection details
        return fault_result(question, fault_reason(exc))
    if not well_formed(result):
        return fault_result(question, "unexpected_error")
    return result
