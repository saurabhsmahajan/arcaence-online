"""The words a customer gets after the privacy agent has finished. Fixed text, written here, never by a model.

The model never writes to the customer. Each reply says only what code knows to be true, and the most important
rule is what it never says: no reply says that anything has been deleted or sent. The tools only open or cancel a
request, and a person decides everything else.
  requested     a request was opened: the tool returned a request id and the kind. The reply says it was opened,
                that a person looks at it first, and that nothing has been deleted or sent yet.
  cancelled     an open deletion request was stopped: the tool returned its id. Nothing was deleted.
  refused       says what is true of the customer's own account (an open request exists, none is open) or that this
                is not something the desk can do. It never says anything about another person's account.
  needs_person  asks which request the customer means, says what the desk can do, or hands over to a person.
                "passed to our team" is said only when the case really was queued.
  an unclear result (the tool raised, or returned something unexpected) never says the request was recorded.
Nothing from the customer's message, the request records, the export counts or the model's output is copied into a
reply, and the tool's own next_step text is never used.
"""

OPENED_DELETION = ("I have opened a request to delete your account and personal data. Nothing has been deleted. "
                   "A person will review it first, and there is a waiting period in which you can cancel it.")
OPENED_EXPORT = ("I have opened a request for a copy of your personal data. Nothing has been sent. "
                 "A person will confirm your identity first and then send it.")
CANCELLED = "Your deletion request has been cancelled. Nothing was deleted."
ALREADY_OPEN = "You already have an open request of this kind, and our team is looking at it. There is nothing more to do."
NOTHING_TO_CANCEL = "There is no open deletion request on your account, so there is nothing to cancel."
NOT_YOURS = "I can only open requests about your own account. The Help Centre can help with anything else."
REFUSED = "I'm sorry, I can't do that here. The Help Centre can look at it."
ASK_WHICH = ("I can open a request for a copy of your personal data, or a request to delete your account. "
             "Please tell me which one you would like.")
NOT_SUPPORTED = "I can only open data copy and account deletion requests here. The Help Centre can help with this."
PERSON_QUEUED = "I can't decide this myself, so I have passed it to our team to look at."
PERSON_NOT_QUEUED = ("I'm sorry, I could not pass your message to our team just now. "
                     "Please contact the Help Centre so a person can look at it.")
UNCLEAR = ("I'm sorry, I can't tell whether your request was recorded, so I am not going to say it was. "
           "Please contact the Help Centre so a person can check.")

ALL_REPLIES = (OPENED_DELETION, OPENED_EXPORT, CANCELLED, ALREADY_OPEN, NOTHING_TO_CANCEL, NOT_YOURS, REFUSED, ASK_WHICH,
               NOT_SUPPORTED, PERSON_QUEUED, PERSON_NOT_QUEUED, UNCLEAR)

_UNCLEAR_REASONS = {"tool_error", "unexpected_result", "step_limit"}   # the tool may have run: promise nothing


def privacy_reply(record: dict, queued: bool = False) -> str:
    """The reply for a finished case. `record` is CaseRecord.to_dict(); `queued` says whether the case really
    reached the review queue (only the handler knows)."""
    outcome, reason, kind = record.get("outcome"), record.get("reason") or "", record.get("kind")
    has_id = bool(record.get("request_id"))
    if outcome == "requested":
        if has_id and kind == "deletion":
            return OPENED_DELETION
        if has_id and kind == "export":
            return OPENED_EXPORT
        return UNCLEAR
    if outcome == "cancelled":
        return CANCELLED if has_id and kind == "deletion" else UNCLEAR
    if outcome == "refused":
        return {"request_already_open": ALREADY_OPEN, "no_open_request": NOTHING_TO_CANCEL,
                "not_eligible": NOT_YOURS}.get(reason, REFUSED)
    if outcome == "needs_person":
        if reason == "unclear_request":
            return ASK_WHICH
        if reason == "not_supported":
            return NOT_SUPPORTED
        if reason in _UNCLEAR_REASONS:
            return UNCLEAR
        return PERSON_QUEUED if queued else PERSON_NOT_QUEUED
    return PERSON_QUEUED if queued else PERSON_NOT_QUEUED   # anything unexpected promises nothing it cannot keep
