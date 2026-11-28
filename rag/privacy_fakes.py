"""Fakes shared by the privacy tests: a fake connection that remembers the request tables, and fake privacy code.
Not used outside tests."""
from privacy_tools import PrivacyLocalTools

RID = "1db066c7-fd3a-4560-8387-8ff421aefed0"


class Conn:
    def __init__(self, store):
        self.store, self.rolled, self.closed = store, False, False

    def execute(self, sql, params=()):
        kind = "deletion" if "deletion_requests" in sql else "export"
        rows = [(c, s) for k, c, s in self.store if k == kind]
        return type("R", (), {"fetchall": lambda s: rows})()

    def rollback(self):
        self.rolled = True
        self.store[:] = list(self.committed)

    def close(self):
        self.closed = True


class Privacy:
    def _open(self, conn, kind, cid):
        if any(k == kind and c == cid and s in ("requested", "approved") for k, c, s in conn.store):
            return {"status": "refused", "reason": "request_already_open"}
        conn.store.append((kind, cid, "requested"))
        out = {"status": "requested", "kind": kind, "request_id": RID}
        if kind == "export":
            out["inventory"] = {"orders": 2, "invoices": 1}
        return out

    def request_export(self, conn, cid): return self._open(conn, "export", cid)
    def request_deletion(self, conn, cid): return self._open(conn, "deletion", cid)

    def cancel_deletion(self, conn, cid):
        for i, (k, c, s) in enumerate(conn.store):
            if k == "deletion" and c == cid and s == "requested":
                conn.store[i] = (k, c, "cancelled")
                return {"status": "cancelled", "kind": "deletion", "request_id": RID}
        return {"status": "refused", "reason": "no_open_request"}


def make():
    db, conns = [], []

    def connect():
        c = Conn(db)
        c.committed = list(db)
        conns.append(c)
        return c
    return PrivacyLocalTools(connect, Privacy()), db, conns
