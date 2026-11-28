"""The part of the privacy agent that code runs. No model call here.

The model ends a case in one of two ways: it asks for one privacy tool, or it closes the case itself with a
fixed outcome and reason (close_case). Everything after that is code:

  * the customer id comes from the case record, never from the model, and is the only argument the tool gets;
  * the model gives no arguments to a privacy tool, and a model that sends any is rejected before anything runs;
  * code reads only the status, the kind, the reason code, the request id and the export counts of the result;
  * the case ends when the tool has run: one action per case;
  * a tool that raises is "tool_error", not refused and not requested, because the request may have been opened.

The tools come in as an argument, so tests pass a fake, the eval passes an in-process version and the
service passes the MCP client. A tool is any object with request_data_export(customer_id),
request_account_deletion(customer_id) and cancel_deletion_request(customer_id), each returning a dict.
"""
from privacy_logic import StepLimitReached, close_case_problems, outcome_after_tool, tool_args_problems


def _done(record) -> dict:
    return {"status": "closed", "outcome": record.outcome, "reason": record.reason}


def _step_status(outcome: str) -> str:
    """The step status for the record, read from the outcome code decided on the tool's result."""
    if outcome in ("requested", "cancelled"):
        return "ok"
    if outcome == "refused":
        return "refused"
    return "error"


def run_privacy_tool(tools, record, tool: str, args=None) -> dict:
    """Run the privacy tool the model asked for and finish the case record.

    Returns {"status": "rejected", "problems": [field names]} if the arguments are not valid (the record is not
    finished, nothing ran). Otherwise it finishes the record and returns {"status": "closed", "outcome", "reason"}.
    """
    if record.outcome:
        raise ValueError("the case is already finished")
    problems = tool_args_problems(tool, args)
    if problems:
        return {"status": "rejected", "problems": [field for field, _ in problems]}

    try:
        record.check_budget()
    except StepLimitReached:
        record.finish("needs_person", "step_limit")
        return _done(record)

    try:
        result = getattr(tools, tool)(customer_id=record.customer_id)
    except Exception as exc:
        record.add_step(tool, "error")
        record.finish("needs_person", "tool_error", error=type(exc).__name__)
        return _done(record)

    read = outcome_after_tool(tool, result)
    record.add_step(tool, _step_status(read["outcome"]), read["reason"])
    record.finish(read["outcome"], read["reason"], read["request_id"], read["inventory"])
    return _done(record)


def close_case(record, args) -> dict:
    """The model ends the case itself: refused with not_eligible, or needs_person with unclear_request or not_supported."""
    if record.outcome:
        raise ValueError("the case is already finished")
    problems = close_case_problems(args)
    if problems:
        return {"status": "rejected", "problems": [field for field, _ in problems]}
    record.finish(args["outcome"], args["reason"])
    return _done(record)
