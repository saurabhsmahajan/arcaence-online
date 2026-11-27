"""Shows what the billing agent did on ONE golden row, turn by turn: what the tools returned and what the model
answered. For diagnosis after a miss. It calls the model once per turn. Nothing is kept in any database.
Run from the rag folder:  uv run python probe_billing.py B10"""
import csv
import sys

from dotenv import find_dotenv, load_dotenv

import billing
from billing_tools import local_tools
from run_billing_eval import GOLDEN, ROOT, run_case
from billing_scoring import score_row

load_dotenv(find_dotenv(usecwd=True))
row_id = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: probe_billing.py B10")
with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
    row = next((r for r in csv.DictReader(f) if r["id"] == row_id), None) or sys.exit(f"no row {row_id}")

real = billing._client_get().messages.create


def create(**kw):
    last = kw["messages"][-1]
    if last["role"] == "user" and isinstance(last["content"], list):
        for b in last["content"]:
            print("  tool result :", str(b.get("content"))[:400].replace("\n", " "))
    resp = real(**kw)
    for b in resp.content:
        kind = getattr(b, "type", "?")
        if kind == "tool_use":
            print("  model calls :", b.name, dict(b.input))
        elif kind == "text":
            print("  model says  :", b.text[:400].replace("\n", " "))
        elif kind == "thinking":
            print("  model thinks:", (getattr(b, "thinking", "") or "")[:400].replace("\n", " "))
    return resp


print(f"{row['id']} [{row['category']}] expected={row['expected_outcome']} {row['expected_reasons']}")
print("message:", row["message"])
record, commits, proposals = run_case(row, local_tools(ROOT / "mcp"), create_fn=create)
print("\nrecord  :", record["outcome"], record["reason"], record.get("error", ""))
print("steps   :", [(s["tool"], s["status"], s.get("reason", "")) for s in record["steps"]])
print("commits :", commits, " proposals:", len(proposals))
print("flags   :", score_row(row, record, commits)["flags"])
