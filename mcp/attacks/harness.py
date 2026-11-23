"""Attack harness for gate G2.

It starts the real servers (reader, writer, policy) as child processes and talks to them over stdio, exactly as an
agent would. Each attack is one function that sends hostile input and says whether it was blocked. The runner also
snapshots the money and privacy tables before and after each attack: an attack that changes them has FAILED, even if
the answer looked like a refusal.

Statuses: PASS (blocked), FAIL (not blocked, or the database changed), KNOWN (a documented gap behaved as documented),
SKIP (a server it needs could not be started).
"""
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from mcp import StdioServerParameters
from mcp.client import Client

ATTACKS_DIR = Path(__file__).resolve().parent
MCP_DIR = ATTACKS_DIR.parent
POLICY_DIR = MCP_DIR.parent / "policy_mcp"
sys.path.insert(0, str(MCP_DIR))  # the ops modules (db_write) live next to server.py

import db_write  # noqa: E402

PASS, FAIL, KNOWN, SKIP = "PASS", "FAIL", "KNOWN", "SKIP"

# Tables the harness watches. An attack must leave all of them as they were, unless it says otherwise.
SNAPSHOT_SQL = {
    "refunds": "select count(*) from ops.refunds",
    "cancellations": "select count(*) from ops.cancellations",
    "deletion_requests": "select count(*) from ops.deletion_requests",
    "deletions_approved_or_completed": "select count(*) from ops.deletion_requests where status in ('approved','completed')",
    "export_requests": "select count(*) from ops.export_requests",
}


def snapshot() -> dict[str, int]:
    with db_write.connect() as conn:
        return {name: conn.execute(sql).fetchone()[0] for name, sql in SNAPSHOT_SQL.items()}


def audit_count(tool: str, mode: str, outcome: str, reason: str | None) -> int:
    with db_write.connect() as conn:
        return conn.execute(
            "select count(*) from ops.audit_log where tool=%s and mode=%s and outcome=%s and reason is not distinct from %s",
            (tool, mode, outcome, reason)).fetchone()[0]


def text_of(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


class Ctx:
    """The connections an attack can use. policy is None when that server could not be started."""

    def __init__(self, reader, writer, policy):
        self.reader, self.writer, self.policy = reader, writer, policy

    async def call(self, client, name, args):
        """Return (ok, data). A refused call is not ok, whether the client raises or flags an error."""
        try:
            result = await client.call_tool(name, args)
        except Exception as e:  # noqa: BLE001
            return False, {"error": str(e)}
        text = text_of(result)
        if getattr(result, "is_error", False):
            return False, {"error": text}
        try:
            return True, json.loads(text)
        except ValueError:
            return True, {"raw": text}

    async def tool_names(self, client) -> list[str]:
        return sorted(t.name for t in (await client.list_tools()).tools)


@dataclass
class Attack:
    id: str
    family: str
    name: str
    adr: str
    fn: Callable[[Ctx], Awaitable[tuple[bool, str]]]
    needs: str = ""  # "policy" when the attack needs the policy server
    known_gap: bool = False
    may_change: frozenset = field(default_factory=frozenset)


ATTACKS: list[Attack] = []


def attack(id, family, name, adr, needs="", known_gap=False, may_change=()):
    """Register an attack. The function returns (blocked, detail). For a known gap it returns (True, detail) when the
    gap behaves exactly as documented."""
    def wrap(fn):
        ATTACKS.append(Attack(id, family, name, adr, fn, needs, known_gap, frozenset(may_change)))
        return fn
    return wrap


async def run(select: set[str] | None = None) -> dict:
    """Run the attacks (all, or those whose id starts with a letter in select). Returns the results."""
    results = []
    async with AsyncExitStack() as stack:
        py = sys.executable
        reader = await stack.enter_async_context(Client(StdioServerParameters(
            command=py, args=["server.py"], cwd=str(MCP_DIR), env={"OPS_ROLE": "ops_reader"})))
        writer = await stack.enter_async_context(Client(StdioServerParameters(
            command=py, args=["server.py"], cwd=str(MCP_DIR), env={"OPS_ROLE": "ops_writer"})))
        policy, policy_error = None, ""
        try:
            policy = await stack.enter_async_context(Client(StdioServerParameters(
                command="uv", args=["run", "--project", str(POLICY_DIR), "python", "server.py"], cwd=str(POLICY_DIR))))
        except Exception as e:  # noqa: BLE001
            policy_error = f"{type(e).__name__}: {e}"
        ctx = Ctx(reader, writer, policy)

        for a in ATTACKS:
            if select and a.id[0] not in select:
                continue
            if a.needs == "policy" and policy is None:
                results.append((a, SKIP, f"policy server not started ({policy_error})"))
                continue
            before = snapshot()
            try:
                blocked, detail = await a.fn(ctx)
            except Exception as e:  # noqa: BLE001
                blocked, detail = False, f"the attack itself crashed: {type(e).__name__}: {e}"
            after = snapshot()
            changed = [k for k in before if before[k] != after[k] and k not in a.may_change]
            if changed:
                status, detail = FAIL, f"database changed ({', '.join(f'{k} {before[k]} to {after[k]}' for k in changed)}). {detail}"
            elif blocked:
                status = KNOWN if a.known_gap else PASS
            else:
                status = FAIL
            results.append((a, status, detail))
    return {"results": results}
