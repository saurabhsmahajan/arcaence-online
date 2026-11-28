"""Runs the privacy agent on the privacy golden set and scores it. Run from the rag folder.

  uv run python run_privacy_eval.py --split dev
  uv run python run_privacy_eval.py --split holdout --confirm-holdout     run ONCE, after the agent and rules are frozen
  uv run python run_privacy_eval.py --split all --confirm-holdout

Every case runs in its own database transaction that is rolled back, so no request is kept and every row starts
from the same database. A row with a setup (an open deletion or export request) has it applied first, inside
that transaction. The scorer compares a snapshot of the request tables before and after the agent runs.
Nothing goes to the real review queue. Exit code 1 if the gate fails.
The model is sampled: re-run before reading anything into one miss.
"""
import argparse
import csv
import sys
from pathlib import Path

from case import new_case_id
from privacy_agent import run_privacy
from privacy_scoring import effects, score_row, summarize
from privacy_tools import PrivacyWatch

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "eval" / "golden_set_privacy.csv"
OUT = ROOT / "eval" / "results"


def run_case(row, tools, create_fn=None):
    """Run one golden row. Returns (record dict, effects, calls). `tools` has case() and snapshot()."""
    watched = PrivacyWatch(tools)
    fx = []
    try:
        with tools.case(row["setup"], row["customer_id"]):
            before = tools.snapshot()
            rec = run_privacy(row["message"], new_case_id(), row["customer_id"], watched, create_fn=create_fn)
            fx = effects(before, tools.snapshot())
        record = rec.to_dict()
    except Exception as exc:  # noqa: BLE001 - one broken row must not stop the run; it is scored as an error
        record = {"outcome": "needs_person", "reason": "tool_error", "steps": [], "error": type(exc).__name__}
    return record, fx, watched.calls


def preflight(tools):
    """Stop if the database already holds an open privacy request: every row assumes a clean start."""
    with tools.case():
        open_now = [r for r in tools.snapshot() if r[2] in ("requested", "approved")]
    if open_now:
        sys.exit(f"The database already holds {len(open_now)} open privacy request(s) {open_now}. "
                 "The eval assumes none. Clear them (as the owner) before running.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout", "all"], required=True)
    ap.add_argument("--confirm-holdout", action="store_true", help="needed for holdout or all: the holdout is run once")
    ap.add_argument("--tag", help="also save eval/results/privacy_<tag>_runs.csv")
    args = ap.parse_args()
    if args.split != "dev" and not args.confirm_holdout:
        sys.exit("The holdout is run once, after the agent and the rules are frozen. Add --confirm-holdout to run it.")

    from dotenv import find_dotenv, load_dotenv
    from privacy_tools import local_privacy_tools
    load_dotenv(find_dotenv(usecwd=True))
    tools = local_privacy_tools(ROOT / "mcp")
    preflight(tools)

    with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if args.split == "all" or r["split"] == args.split]
    scores, lines = [], []
    for r in rows:
        record, fx, calls = run_case(r, tools)
        s = score_row(r, record, fx, calls)
        scores.append(s)
        mark = "ok  " if s["passed"] else "MISS"
        extra = f" flags={s['flags']}" if s["flags"] else ""
        did = ",".join(f"{e['change']}:{e['kind']}" for e in fx) or "-"
        print(f"{mark} {r['id']} [{r['category']}] expected={r['expected_outcome']} got={s['outcome']}/{s['reason'] or '-'} "
              f"effects={did}{extra}" + (f" error={record['error']}" if record.get("error") else ""))
        lines.append({"id": r["id"], "split": r["split"], "expected": s["expected"], "outcome": s["outcome"], "reason": s["reason"],
                      "effects": did, "flags": "|".join(s["flags"]), "passed": s["passed"]})
    sm = summarize(scores)
    print(f"\nsplit={args.split}  rows passed: {sm['passed']}/{sm['rows']}  accuracy {sm['accuracy']:.0%}")
    print(f"flags: {sm['flags'] or 'none'}")
    print("GATE:", "PASS" if sm["gate_ok"] else "FAIL")
    if args.tag:
        OUT.mkdir(exist_ok=True)
        path = OUT / f"privacy_{args.tag}_runs.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lines[0]))
            w.writeheader()
            w.writerows(lines)
        print("saved", path.name)
    sys.exit(0 if sm["gate_ok"] else 1)


if __name__ == "__main__":
    main()
