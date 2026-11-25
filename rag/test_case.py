"""Offline tests for case ids. Run from the rag folder: uv run python test_case.py"""
from datetime import datetime, timezone

from case import is_case_id, new_case_id

n = 0


def check(name, cond):
    global n
    n += 1
    assert cond, name
    print("ok ", name)


a = new_case_id()
check("a new id has the right shape", is_case_id(a))
check("the id starts with case_ and today's UTC date",
      a.startswith("case_" + datetime.now(timezone.utc).strftime("%Y%m%d") + "_"))
check("the date part follows the time given",
      new_case_id(datetime(2026, 11, 24, 23, 59, tzinfo=timezone.utc)).startswith("case_20261124_"))
ids = {new_case_id() for _ in range(5000)}
check("5000 ids are all different", len(ids) == 5000)
check("a missing prefix is refused", not is_case_id("20261125_9f3a0c41b7de"))
check("upper-case hex is refused", not is_case_id("case_20261125_9F3A0C41B7DE"))
check("too short is refused", not is_case_id("case_20261125_9f3a0c41b7d"))
check("too long is refused", not is_case_id("case_20261125_9f3a0c41b7dee"))
check("a trailing newline is refused", not is_case_id("case_20261125_9f3a0c41b7de\n"))
check("full-width digits are refused", not is_case_id("case_２０２６１１２５_9f3a0c41b7de"))
check("SQL text is refused", not is_case_id("case_20261125_9f3a0c41b7de'; drop table x;--"))
check("None is refused", not is_case_id(None))
check("a number is refused", not is_case_id(20261125))
print(f"\n{n} checks passed")
