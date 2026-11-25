"""Case id: one id per customer message, made by the server and never taken from the caller.

Shape: case_YYYYMMDD_ plus 12 lowercase hex characters, for example case_20261125_9f3a0c41b7de.
The date is UTC and makes ids easy to sort and to find by day. The 12 hex characters (48 random bits)
make a clash between two ids on one day practically impossible at this scale. Later steps store the
id as a primary key, so a clash would be refused there as well.
"""
import re
import secrets
from datetime import datetime, timezone

CASE_ID = re.compile(r"case_[0-9]{8}_[0-9a-f]{12}")  # [0-9], not \d: ASCII digits only (ADR-047)


def new_case_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"case_{now:%Y%m%d}_{secrets.token_hex(6)}"


def is_case_id(value) -> bool:
    return isinstance(value, str) and CASE_ID.fullmatch(value) is not None
