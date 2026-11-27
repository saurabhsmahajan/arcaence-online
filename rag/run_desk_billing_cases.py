"""Runs the desk cases end to end through the handler with billing in shadow mode, and scores them. Run from the rag folder.

  uv run python run_desk_billing_cases.py --tag desk1

Each case goes through the real pipeline: classifier, answer, triage and the billing agent. The customer id and "today"
come from the case file (the stand-in for the trusted caller and the clock, because the synthetic orders are fixed in time).
Billing runs on the rolled-back adapter. The review queue and the traces are stand-ins, so nothing is kept anywhere.
Exit code 1 if the gate fails. The model is sampled: read a miss with probe_billing.py before changing anything.
"""
import argparse
import csv
import sys
import time
from pathlib import Path

from billing_shadow import shadow_billing
from desk_billing_scoring import score_case, summarize
from handler import handle_message

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "eval" / "desk_cases_billing.csv"
OUT = ROOT / "eval" / "results"


def run_case(case, tools_fn, **handler_args):
    """One case through the handler. `tools_fn()` returns a fresh rolled-back adapter. Returns (result, latency_ms)."""
    def billing_fn(question, case_id, customer_id):
        return shadow_billing(question, case_id, customer_id, tools_fn(), today=case["as_of"])

    started = time.perf_counter()
    result = handle_message(case["message"], enqueue_fn=lambda r: "stand-in", route_fn=lambda p: "stand-in",
                            trace_fn=lambda r, ms: None, customer_id=case["customer_id"], billing_fn=billing_fn,
                            **handler_args)
    return result, int((time.perf_counter() - started) * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="also save eval/results/<tag>_desk_billing.csv")
    args = ap.parse_args()

    from dotenv import find_dotenv, load_dotenv
    from billing_tools import local_tools
    load_dotenv(find_dotenv(usecwd=True))

    with open(CASES, newline="", encoding="utf-8-sig") as f:
        cases = list(csv.DictReader(f))
    scores, lines = [], []
    for c in cases:
        result, ms = run_case(c, lambda: local_tools(ROOT / "mcp"))
        s = score_case(c, result)
        scores.append(s)
        b = result["billing"]
        mark = "ok  " if s["passed"] else "MISS"
        print(f"{mark} {c['id']} [{c['category']}] label={result.get('label') or '-'} intent={s['intent'] or '-'} billing="
              + (f"{b['outcome']}/{b['reason'] or '-'} steps={b['steps']} would_refund={b['would_refund']} would_queue={b['would_queue']}"
                 if b["ran"] else f"not run ({b['skipped'] or 'error ' + b['error']})")
              + f" {ms}ms" + (f" flags={s['flags']}" if s["flags"] else ""))
        if b["ran"]:
            print(f"       reply preview: {b['preview']}")
        lines.append({"id": c["id"], "intent": s["intent"], "ran": s["ran"], "outcome": s["outcome"], "reason": s["reason"],
                      "would_refund": b["would_refund"], "would_queue": b["would_queue"], "latency_ms": ms,
                      "flags": "|".join(s["flags"]), "passed": s["passed"]})
    sm = summarize(scores)
    print(f"\ncases passed: {sm['passed']}/{sm['rows']}  accuracy {sm['accuracy']:.0%}")
    print(f"flags: {sm['flags'] or 'none'}")
    print("GATE:", "PASS" if sm["gate_ok"] else "FAIL")
    if args.tag:
        OUT.mkdir(exist_ok=True)
        path = OUT / f"{args.tag}_desk_billing.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lines[0]))
            w.writeheader()
            w.writerows(lines)
        print("saved", path.name)
    sys.exit(0 if sm["gate_ok"] else 1)


if __name__ == "__main__":
    main()
