"""The part of the billing agent that code runs. No model call here.

The model ends a case in one of two ways: it asks for a refund (request_refund) or it closes the case itself
with a fixed outcome and reason (close_case). Everything after that is code:

  * the customer id comes from the case record, never from the model;
  * code runs the dry run, reads only the status and reason code, and commits with the token;
  * the token lives inside settle_refund and is never returned, recorded or shown to the model;
  * a refund over the cap is queued as a proposal for a person, once, and the case is queued only if that write worked;
  * a commit that raises is "unclear", not refused and not settled, because the refund may have been recorded.

The tools come in as an argument, so tests pass a fake, the eval passes an in-process version and the
service passes the MCP client. A tool is any object with issue_refund(customer_id, order_id, amount,
clause_doc, clause_id, dry_run, confirm_token) that returns a dict.
"""
from billing_logic import (LABEL, StepLimitReached, close_case_problems, next_after_dry_run, outcome_after_commit,
                           refund_args_problems, refund_proposal)


def _status(result) -> tuple[str, str]:
    """(step status, reason code) read from a tool result. Anything unexpected is an error step."""
    if isinstance(result, dict) and result.get("status") in ("preview", "done", "refused"):
        reason = result.get("reason")
        return result["status"], reason if isinstance(reason, str) and LABEL.fullmatch(reason) else ""
    return "error", ""


def _issue(tools, record, args, dry_run: bool, token):
    return tools.issue_refund(
        customer_id=record.customer_id, order_id=args["order_id"], amount=args["amount"],
        clause_doc=args.get("clause_doc"), clause_id=args.get("clause_id"),
        dry_run=dry_run, confirm_token=token,
    )


def _done(record) -> dict:
    return {"status": "closed", "outcome": record.outcome, "reason": record.reason}


def settle_refund(tools, record, args, question: str, enqueue_fn) -> dict:
    """Run the refund the model asked for and finish the case record.

    Returns {"status": "rejected", "problems": [field names]} if the arguments are not valid (the record is not
    finished, nothing ran). Otherwise it finishes the record and returns {"status": "closed", "outcome", "reason"}.
    enqueue_fn(proposal) adds a proposed action to the review queue and returns its item id.
    """
    if record.outcome:
        raise ValueError("the case is already finished")
    problems = refund_args_problems(args)
    if problems:
        return {"status": "rejected", "problems": [field for field, _ in problems]}

    try:
        record.check_budget(2)               # a dry run and a commit both have to fit
    except StepLimitReached:
        record.finish("needs_person", "step_limit")
        return _done(record)

    try:
        dry = _issue(tools, record, args, True, None)
    except Exception as exc:
        record.add_step("issue_refund", "error", mode="dry_run")
        record.finish("needs_person", "tool_error", error=type(exc).__name__)
        return _done(record)
    status, reason = _status(dry)
    record.add_step("issue_refund", status, reason, "dry_run")

    action, why = next_after_dry_run(dry)
    if action == "commit":
        token = dry["token"]                 # stays in this function
        try:
            result = _issue(tools, record, args, False, token)
        except Exception as exc:
            record.add_step("issue_refund", "error", mode="commit")
            record.finish("needs_person", "commit_unclear", error=type(exc).__name__)
            return _done(record)
        status, reason = _status(result)
        record.add_step("issue_refund", status, reason, "commit")
        action, why = outcome_after_commit(result)
        if action == "settled":
            record.finish("settled")
            return _done(record)
        if action == "queued":
            action = "queue"
    if action == "queue":
        try:
            item_id = enqueue_fn(refund_proposal(record.case_id, record.customer_id, question, args))
            if item_id is None:
                raise ValueError("the queue returned no item id")
        except Exception as exc:
            record.finish("needs_person", "queue_failed", error=type(exc).__name__)   # never claim a queue that did not happen
            return _done(record)
        record.finish("queued", why, item_id)
        return _done(record)
    record.finish(action, why)
    return _done(record)


def close_case(record, args) -> dict:
    """The model ends the case itself: refused with not_eligible, or needs_person with one of three reasons."""
    if record.outcome:
        raise ValueError("the case is already finished")
    problems = close_case_problems(args)
    if problems:
        return {"status": "rejected", "problems": [field for field, _ in problems]}
    record.finish(args["outcome"], args["reason"])
    return _done(record)
