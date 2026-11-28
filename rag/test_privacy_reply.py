"""Tests for the privacy reply words. Pure: no model, no database, no keys."""
import itertools

import privacy_reply as pr
from privacy_logic import ALLOWED_REASONS, OUTCOMES
from privacy_reply import ALL_REPLIES, privacy_reply

n = 0


def check(ok, label):
    global n
    assert ok, "FAILED: " + label
    n += 1


RID = "1db066c7-fd3a-4560-8387-8ff421aefed0"

# --- requested / cancelled -------------------------------------------------------------------------------------
check(privacy_reply({"outcome": "requested", "kind": "deletion", "request_id": RID}) == pr.OPENED_DELETION, "a deletion request says it was opened")
check(privacy_reply({"outcome": "requested", "kind": "export", "request_id": RID}) == pr.OPENED_EXPORT, "an export request says it was opened")
check(privacy_reply({"outcome": "cancelled", "kind": "deletion", "request_id": RID}) == pr.CANCELLED, "a cancel says so")
for rec in ({"outcome": "requested", "kind": "deletion"}, {"outcome": "requested", "kind": "", "request_id": RID},
            {"outcome": "requested", "kind": "other", "request_id": RID}, {"outcome": "cancelled", "kind": "export", "request_id": RID},
            {"outcome": "cancelled", "kind": "deletion"}):
    check(privacy_reply(rec) == pr.UNCLEAR, f"no request id or an odd kind promises nothing: {rec}")

# --- refused ---------------------------------------------------------------------------------------------------
check(privacy_reply({"outcome": "refused", "reason": "request_already_open"}) == pr.ALREADY_OPEN, "a duplicate says one is open")
check(privacy_reply({"outcome": "refused", "reason": "no_open_request"}) == pr.NOTHING_TO_CANCEL, "a cancel with nothing open says so")
check(privacy_reply({"outcome": "refused", "reason": "not_eligible"}) == pr.NOT_YOURS, "another person's account gets the own-account words")
check(privacy_reply({"outcome": "refused", "reason": "customer_not_found"}) == pr.REFUSED, "an unknown customer gets the plain refusal")
check(privacy_reply({"outcome": "refused", "reason": "weird"}) == pr.REFUSED, "an unknown refusal reason gets the plain refusal")
check("account" not in pr.NOT_YOURS.replace("your own account", ""), "the not-yours words never mention another account")

# --- needs_person ----------------------------------------------------------------------------------------------
check(privacy_reply({"outcome": "needs_person", "reason": "unclear_request"}) == pr.ASK_WHICH, "unclear asks which request")
check(privacy_reply({"outcome": "needs_person", "reason": "not_supported"}) == pr.NOT_SUPPORTED, "not supported says what the desk can do")
for reason in ("tool_error", "unexpected_result", "step_limit"):
    check(privacy_reply({"outcome": "needs_person", "reason": reason}, queued=True) == pr.UNCLEAR, f"{reason}: never says it was recorded, even if queued")
for reason in ("model_error", "model_truncated", "no_decision", "turn_limit", ""):
    check(privacy_reply({"outcome": "needs_person", "reason": reason}, queued=True) == pr.PERSON_QUEUED, f"{reason or 'no reason'}: queued says it was passed on")
    check(privacy_reply({"outcome": "needs_person", "reason": reason}, queued=False) == pr.PERSON_NOT_QUEUED, f"{reason or 'no reason'}: not queued promises nothing")

# --- anything unexpected ---------------------------------------------------------------------------------------
for rec in ({}, {"outcome": None}, {"outcome": "approved"}, {"outcome": "REQUESTED"}, {"outcome": 5}):
    check(privacy_reply(rec) == pr.PERSON_NOT_QUEUED, f"an unexpected record promises nothing: {rec}")

# --- the words themselves --------------------------------------------------------------------------------------
check(all(isinstance(t, str) and t.strip() == t and len(t) < 300 for t in ALL_REPLIES), "every reply is plain, trimmed and short")
check(len(set(ALL_REPLIES)) == len(ALL_REPLIES), "no two replies are the same")
for text in ALL_REPLIES:
    low = text.lower()
    check("has been deleted" not in low.replace("nothing has been deleted", "") and "was deleted" not in low.replace("nothing was deleted", ""),
          f"no reply says anything was deleted: {text[:30]}")
    check("has been sent" not in low.replace("nothing has been sent", "") and "we have sent" not in low and "i have sent" not in low,
          f"no reply says anything was sent: {text[:30]}")
    check(not any(c.isdigit() for c in text) and "cust_" not in text and "@" not in text, f"no digits, ids or addresses in a reply: {text[:30]}")
check("nothing has been deleted" in pr.OPENED_DELETION.lower() and "nothing has been sent" in pr.OPENED_EXPORT.lower(),
      "an opened request says in words that nothing has happened yet")
check("review" in pr.OPENED_DELETION and "confirm your identity" in pr.OPENED_EXPORT, "and says a person decides next")

# --- every combination gives one of the fixed replies ----------------------------------------------------------
reasons = sorted({r for rs in ALLOWED_REASONS.values() for r in rs} | {"", "weird", "customer_not_found"})
seen = set()
for outcome, reason, kind, rid, queued in itertools.product(sorted(OUTCOMES) + ["x"], reasons, ["deletion", "export", "", "zzz"], [None, RID], [False, True]):
    seen.add(privacy_reply({"outcome": outcome, "reason": reason, "kind": kind, "request_id": rid}, queued))
check(seen <= set(ALL_REPLIES), "every combination of outcome, reason, kind and id gives one of the fixed replies")
check(seen == set(ALL_REPLIES), "and every fixed reply can be reached")
print(f"PRIVACY REPLY TESTS: {n} checks passed")
