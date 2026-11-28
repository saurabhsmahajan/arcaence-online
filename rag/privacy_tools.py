"""Tool adapters for the privacy agent: what the flow calls, and where the answers come from.

The flow (privacy_flow.py) wants three plain calls: request_data_export(customer_id),
request_account_deletion(customer_id) and cancel_deletion_request(customer_id). This file is the one place
that knows how those are served in the evaluation.

PrivacyLocalTools serves them in-process. It runs the same privacy code the MCP server runs (mcp/privacy.py),
but on one connection per case that is ALWAYS rolled back. A request opened in a test would stay open and every
later run would be refused as request_already_open; with a rollback every case starts from the same database.
It can also set a case up (an open deletion or export request) and take a snapshot of the request tables, so the
scorer can see what really happened to the database, not what the agent said.

The MCP-client adapter (the real path, over stdio) is a later step and has the same three methods.
"""
import re
from contextlib import contextmanager

SETUPS = ("none", "open_deletion", "open_export")
CUSTOMER_ID = re.compile(r"cust_[0-9]{3}")
TABLES = (("deletion", "ops.deletion_requests"), ("export", "ops.export_requests"))


class PrivacyLocalTools:
    """In-process tools for the evaluation. Use one case at a time: `with tools.case(setup, customer): ...`."""

    def __init__(self, connect, privacy):
        self._connect, self._privacy, self._conn = connect, privacy, None

    @contextmanager
    def case(self, setup: str = "none", customer_id: str | None = None):
        """One case, one connection, always rolled back and closed, whatever happens inside."""
        if self._conn is not None:
            raise RuntimeError("a case is already open")
        if setup not in SETUPS:
            raise ValueError(f"setup {setup!r} is not one of {SETUPS}")
        if setup != "none" and not (isinstance(customer_id, str) and CUSTOMER_ID.fullmatch(customer_id)):
            raise ValueError("a setup needs a valid customer id")
        self._conn = self._connect()
        try:
            self._set_up(setup, customer_id)
            yield self
        finally:
            conn, self._conn = self._conn, None
            try:
                conn.rollback()
            finally:
                conn.close()

    def _set_up(self, setup, customer_id):
        if setup == "none":
            return
        fn = self._privacy.request_deletion if setup == "open_deletion" else self._privacy.request_export
        result = fn(self._conn, customer_id)
        if not (isinstance(result, dict) and result.get("status") == "requested"):
            raise RuntimeError(f"setup {setup} did not open a request (is one already open in the database?)")

    def snapshot(self) -> list[tuple[str, str, str]]:
        """Every request in the two tables as (kind, customer_id, status), for every customer, sorted."""
        if self._conn is None:
            raise RuntimeError("snapshot outside a case")
        rows = []
        for kind, table in TABLES:
            for customer_id, status in self._conn.execute(f"select customer_id, status from {table}").fetchall():
                rows.append((kind, customer_id, status))
        return sorted(rows)

    def _need_case(self):
        if self._conn is None:
            raise RuntimeError("privacy tool outside a case: nothing would be rolled back")
        return self._conn

    def request_data_export(self, customer_id):
        return self._privacy.request_export(self._need_case(), customer_id)

    def request_account_deletion(self, customer_id):
        return self._privacy.request_deletion(self._need_case(), customer_id)

    def cancel_deletion_request(self, customer_id):
        return self._privacy.cancel_deletion(self._need_case(), customer_id)


class PrivacyWatch:
    """Wraps tools and logs every call as (tool, customer_id). The scorer checks the log against the case."""

    def __init__(self, tools):
        self._tools, self.calls = tools, []

    def request_data_export(self, customer_id):
        self.calls.append(("request_data_export", customer_id))
        return self._tools.request_data_export(customer_id)

    def request_account_deletion(self, customer_id):
        self.calls.append(("request_account_deletion", customer_id))
        return self._tools.request_account_deletion(customer_id)

    def cancel_deletion_request(self, customer_id):
        self.calls.append(("cancel_deletion_request", customer_id))
        return self._tools.cancel_deletion_request(customer_id)


def local_privacy_tools(mcp_dir):
    """Wire PrivacyLocalTools to the real code and database. Needs OPS_WRITER_DATABASE_URL (the mcp/.env file).
    Imports happen here so the tests need no database. The MCP server's privacy.py is loaded from its file, because
    this folder has its own agent module and a plain import could pick the wrong one."""
    import importlib.util
    import sys
    from pathlib import Path

    folder = Path(mcp_dir).resolve()
    if str(folder) not in sys.path:
        sys.path.append(str(folder))    # appended, so nothing in this folder can be shadowed (audit, actions, db_write)
    import db_write

    spec = importlib.util.spec_from_file_location("mcp_privacy", folder / "privacy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return PrivacyLocalTools(db_write.connect, module)
