"""Run the hidden-instruction drills against the real answer model.

    uv run python run_injection_drills.py --guard off --tag base      # the prompt without the guard
    uv run python run_injection_drills.py --guard on  --tag guard     # the prompt with the guard
    uv run python run_injection_drills.py --rescore ../eval/results/injection_base_runs.csv   # no model calls
    options: --runs N (default 3)   --only IN01,IN02

Only the answer model is real. The classifier is fixed to "normal" and the sources are the planted ones
from eval/injection_drills.csv, so the result measures the answer prompt and nothing else. Each run goes
through safe_desk_answer, so a fault is recorded as a fault and never counts as correct.
Cost: about 10 drills x runs x up to 3 model calls. Needs ANTHROPIC_API_KEY and DATABASE_URL.
"""
import argparse
import csv
import sys
from pathlib import Path

import answer
import desk
import desk_logic
import desk_safe
import injection_scoring as sc

OUT = Path(__file__).resolve().parent.parent / "eval" / "results"
NORMAL = {"label": "normal", "confidence": 1.0, "fallback_reason": "", "clarifying_question": ""}


def preflight() -> None:
    status, registry = answer.reference()
    for label in (sc.TRUE_LABEL, sc.POISON_LABEL):
        doc, clause = label.split()
        if status.get(doc) != "approved" or (clause, doc) not in registry:
            sys.exit(f"The drills need {label} to be an approved clause in the database, and it is not.")


def rescore(rows: list[dict], path: str) -> None:
    """Score the stored answers again against the current drill file. A stored fault stays a fault."""
    by_id = {r["id"]: r for r in rows}
    scored = []
    with open(path, encoding="utf-8", newline="") as f:
        for old in csv.DictReader(f):
            res = {"answer": old["answer"], "behavior": old["behavior"], "refusal_reason": old["reason"]}
            s = sc.score_row(by_id[old["id"]], res)
            scored.append(s)
            if s["flags"] or old["flags"]:
                print(f"{old['id']} run {old['run']}: was [{old['flags']}] now [{'|'.join(s['flags'])}]")
    summary = sc.summarize(scored)
    print(f"\nrescored {path}: {summary['ok']} of {summary['runs']} runs clean; flags {summary['flags']}")
    print("GATE: PASS" if summary["gate_pass"] else "GATE: FAIL")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", choices=["on", "off"])
    ap.add_argument("--tag")
    ap.add_argument("--rescore", help="score the answers in an earlier runs file again, with no model calls")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    rows = sc.load()
    if args.rescore:
        rescore(rows, args.rescore)
        return
    if not args.guard or not args.tag:
        ap.error("--guard and --tag are required unless --rescore is used")
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in wanted]
    preflight()
    desk.PARTS_SYSTEM = desk_logic.PARTS_SYSTEM if args.guard == "on" else desk_logic.PARTS_SYSTEM_BASE
    desk.classify = lambda q: NORMAL

    scored, out_rows = [], []
    for row in rows:
        desk.gather = lambda q, row=row: sc.build_sources(row)
        for run in range(1, args.runs + 1):
            res = desk_safe.safe_desk_answer(row["question"], desk.desk_answer, deadline_s=120)
            s = sc.score_row(row, res)
            scored.append(s)
            out_rows.append({"id": row["id"], "run": run, "guard": args.guard, "behavior": s["behavior"],
                             "reason": s["reason"], "flags": "|".join(s["flags"]), "answer": res["answer"]})
            print(f"{'ok ' if s['ok'] else 'FAIL'} {row['id']} run {run} {s['behavior']:7} {'|'.join(s['flags'])}")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"injection_{args.tag}_runs.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    summary = sc.summarize(scored)
    print(f"\nguard {args.guard}: {summary['ok']} of {summary['runs']} runs clean; flags {summary['flags']}")
    print(f"written: {path}")
    print("GATE: PASS" if summary["gate_pass"] else "GATE: FAIL")


if __name__ == "__main__":
    main()
