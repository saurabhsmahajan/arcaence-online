"""Runs triage on the triage golden set and scores it. Run from the rag folder.

  uv run python run_triage_eval.py --split dev        tune on this
  uv run python run_triage_eval.py --split holdout    used on 27 Nov and then read for diagnosis: now a second dev set
  uv run python run_triage_eval.py --split holdout2   fresh messages, written after the fixes: run ONCE
  uv run python run_triage_eval.py --split all

Exit code 1 if the gate fails (a false route, an invented fact, or intent accuracy under 90%).
The model is sampled, so re-run before reading anything into one miss.
"""
import argparse
import csv
import sys
from pathlib import Path

from triage import triage
from triage_scoring import got_facts, score_row, summarize

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "golden_set_triage.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout", "holdout2", "all"], required=True)
    split = ap.parse_args().split
    with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if split == "all" or r["split"] == split]
    scores = []
    for r in rows:
        got = triage(r["message"])
        s = score_row(r, got)
        scores.append(s)
        mark = "ok  " if s["passed"] else "MISS"
        extra = f" flags={s['flags']}" if s["flags"] else ""
        print(f"{mark} {r['id']} [{r['category']}] expected={r['expected_intent']} got={got['intent']} "
              f"facts={got_facts(got)}{extra}" + (f" dropped={got['dropped_facts']}" if got.get("dropped_facts") else "") + (f" ({got['fallback_reason']})" if got["fallback"] else ""))
    r = summarize(scores)
    print(f"\nsplit={split}  single-request rows: {r['passed']}/{r['rows']} passed, "
          f"intent accuracy {r['intent_accuracy']:.0%}")
    print(f"flags: {r['flags'] or 'none'}")
    print(f"multi rows (reported apart): {r['multi_passed']}/{r['multi_rows']} passed")
    print("GATE:", "PASS" if r["gate_ok"] else "FAIL")
    sys.exit(0 if r["gate_ok"] else 1)


if __name__ == "__main__":
    main()
