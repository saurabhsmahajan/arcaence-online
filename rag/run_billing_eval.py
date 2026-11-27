"""Runs the billing agent on the billing golden set and scores it. Run from the rag folder.

  uv run python run_billing_eval.py --split dev
  uv run python run_billing_eval.py --split holdout --confirm-holdout     run ONCE, after the agent and rules are frozen
  uv run python run_billing_eval.py --split all --confirm-holdout

Every case runs in its own database transaction that is rolled back, so no refund is kept and the cap is the
same for every row. Nothing goes to the real review queue. Exit code 1 if the gate fails.
The model is sampled: re-run before reading anything into one miss.
"""
import argparse
import csv
import sys
from pathlib import Path

from billing import run_billing
from billing_scoring import score_row, summarize
from case import new_case_id

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "eval" / "golden_set_billing.csv"
OUT = ROOT / "eval" / "results"


class Watch:
    """Wraps the tools and notes every commit that went through, so the score reads what happened to the money."""

    def __init__(self, tools):
        self._tools, self.commits = tools, []

    def get_order(self, order_id):
        return self._tools.get_order(order_id)

    def get_account(self, customer_id):
        return self._tools.get_account(customer_id)

    def search_policy(self, query):
        return self._tools.search_policy(query)

    def issue_refund(self, customer_id, order_id, amount, clause_doc, clause_id, dry_run, confirm_token):
        result = self._tools.issue_refund(customer_id, order_id, amount, clause_doc, clause_id, dry_run, confirm_token)
        if not dry_run:
            res = result if isinstance(result, dict) else {}
            self.commits.append({"status": res.get("status"), "reason": res.get("reason"), "amount": res.get("amount"),
                                 "order_id": res.get("order_id"), "clause": f"{clause_doc} {clause_id}"})
        return result


class Queue:
    """Stands in for the review queue: keeps what would have been queued and hands back an id."""

    def __init__(self):
        self.items = []

    def __call__(self, proposal):
        self.items.append(proposal)
        return len(self.items)


def run_case(row, tools, create_fn=None):
    """Run one golden row. Returns (record dict, commits, proposals). `tools` has a case() context manager."""
    watched, queue = Watch(tools), Queue()
    try:
        with tools.case():
            rec = run_billing(row["message"], new_case_id(), row["customer_id"], row["as_of"], watched, queue,
                              create_fn=create_fn)
        record = rec.to_dict()
    except Exception as exc:  # noqa: BLE001 - one broken row must not stop the run; it is scored as an error
        record = {"outcome": "needs_person", "reason": "tool_error", "steps": [], "error": type(exc).__name__}
    return record, watched.commits, queue.items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout", "all"], required=True)
    ap.add_argument("--confirm-holdout", action="store_true", help="needed for holdout or all: the holdout is run once")
    ap.add_argument("--tag", help="also save eval/results/billing_<tag>_runs.csv")
    args = ap.parse_args()
    if args.split != "dev" and not args.confirm_holdout:
        sys.exit("The holdout is run once, after the agent and the rules are frozen. Add --confirm-holdout to run it.")

    from dotenv import find_dotenv, load_dotenv
    from billing_tools import local_tools
    load_dotenv(find_dotenv(usecwd=True))
    tools = local_tools(ROOT / "mcp")

    with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if args.split == "all" or r["split"] == args.split]
    scores, lines = [], []
    for r in rows:
        record, commits, proposals = run_case(r, tools)
        s = score_row(r, record, commits)
        scores.append(s)
        mark = "ok  " if s["passed"] else "MISS"
        extra = f" flags={s['flags']}" if s["flags"] else ""
        refunded = f" refunded={commits[-1]['amount']} {commits[-1]['order_id']}" if commits and commits[-1]["status"] == "done" else ""
        print(f"{mark} {r['id']} [{r['category']}] expected={r['expected_outcome']} got={s['outcome']}/{s['reason'] or '-'} "
              f"steps={len(record.get('steps', []))}{refunded}{extra}" + (f" error={record['error']}" if record.get("error") else ""))
        lines.append({"id": r["id"], "split": r["split"], "expected": s["expected"], "outcome": s["outcome"], "reason": s["reason"],
                      "steps": len(record.get("steps", [])), "flags": "|".join(s["flags"]), "passed": s["passed"]})
    sm = summarize(scores)
    print(f"\nsplit={args.split}  rows passed: {sm['passed']}/{sm['rows']}  accuracy {sm['accuracy']:.0%}")
    print(f"flags: {sm['flags'] or 'none'}")
    print("GATE:", "PASS" if sm["gate_ok"] else "FAIL")
    if args.tag:
        OUT.mkdir(exist_ok=True)
        path = OUT / f"billing_{args.tag}_runs.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lines[0]))
            w.writeheader()
            w.writerows(lines)
        print("saved", path.name)
    sys.exit(0 if sm["gate_ok"] else 1)


if __name__ == "__main__":
    main()
