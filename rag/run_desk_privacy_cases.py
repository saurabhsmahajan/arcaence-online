"""Runs the privacy desk cases end to end through the handler with privacy in shadow mode, and scores them. Run from the rag folder.

  uv run python run_desk_privacy_cases.py --tag desk1

Each case goes through the real pipeline: classifier, answer, triage and the privacy agent. The customer id comes from the case
file (the stand-in for the trusted caller). A case with a setup (an open deletion or export request) has it applied first, inside
the same rolled-back transaction. Privacy runs on the rolled-back adapter, so nothing is kept. The review queue and the traces are
stand-ins. Billing is a spy: if the handler calls it, it records that and returns a harmless hand-off, so a privacy message that
reaches billing is flagged and a refund message is never really run.
Exit code 1 if the gate fails. The model is sampled: re-run before reading anything into one miss.
"""
import argparse
import csv
import sys
import time
from pathlib import Path

from desk_privacy_scoring import score_case, summarize
from handler import handle_message
from privacy_shadow import shadow_privacy

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "eval" / "desk_cases_privacy.csv"
OUT = ROOT / "eval" / "results"
SPY_RECORD = {"outcome": "needs_person", "reason": "", "steps": [], "error": ""}


def run_case(case, tools_fn, privacy_create_fn=None, **handler_args):
    """One case through the handler. `tools_fn()` returns a fresh rolled-back adapter. Returns (result, latency_ms)."""
    def privacy_fn(question, case_id, customer_id):
        return shadow_privacy(question, case_id, customer_id, tools_fn(), create_fn=privacy_create_fn, setup=case["setup"])

    def billing_spy(question, case_id, customer_id):
        return {"record": dict(SPY_RECORD), "refund": None, "proposals": []}

    started = time.perf_counter()
    result = handle_message(case["message"], enqueue_fn=lambda r: "stand-in", route_fn=lambda p: "stand-in",
                            trace_fn=lambda r, ms: None, customer_id=case["customer_id"], billing_fn=billing_spy,
                            privacy_fn=privacy_fn, **handler_args)
    return result, int((time.perf_counter() - started) * 1000)


def preflight(tools):
    """Stop if the database already holds an open privacy request: every case assumes a clean start."""
    with tools.case():
        open_now = [r for r in tools.snapshot() if r[2] in ("requested", "approved")]
    if open_now:
        sys.exit(f"The database already holds {len(open_now)} open privacy request(s) {open_now}. "
                 "The cases assume none. Reject them (as the owner) before running.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="also save eval/results/<tag>_desk_privacy.csv")
    args = ap.parse_args()

    from dotenv import find_dotenv, load_dotenv
    from privacy_tools import local_privacy_tools
    load_dotenv(find_dotenv(usecwd=True))
    preflight(local_privacy_tools(ROOT / "mcp"))

    with open(CASES, newline="", encoding="utf-8-sig") as f:
        cases = list(csv.DictReader(f))
    scores, lines = [], []
    for c in cases:
        result, ms = run_case(c, lambda: local_privacy_tools(ROOT / "mcp"))
        s = score_case(c, result)
        scores.append(s)
        p = result["privacy"]
        mark = "ok  " if s["passed"] else "MISS"
        print(f"{mark} {c['id']} [{c['category']}] label={result.get('label') or '-'} intent={s['intent'] or '-'} privacy="
              + (f"{p['outcome']}/{p['reason'] or '-'} kind={p['kind'] or '-'} steps={p['steps']} would_open={p['would_open']} would_cancel={p['would_cancel']}"
                 if p["ran"] else f"not run ({p['skipped'] or 'error ' + p['error']})")
              + f" billing_ran={result['billing']['ran']} {ms}ms" + (f" flags={s['flags']}" if s["flags"] else ""))
        if p["ran"]:
            print(f"       reply preview: {p['preview']}")
        lines.append({"id": c["id"], "intent": s["intent"], "ran": s["ran"], "outcome": s["outcome"], "reason": s["reason"],
                      "would_open": p["would_open"], "would_cancel": p["would_cancel"], "billing_ran": result["billing"]["ran"],
                      "latency_ms": ms, "flags": "|".join(s["flags"]), "passed": s["passed"]})
    sm = summarize(scores)
    print(f"\ncases passed: {sm['passed']}/{sm['rows']}  accuracy {sm['accuracy']:.0%}")
    print(f"flags: {sm['flags'] or 'none'}")
    print("GATE:", "PASS" if sm["gate_ok"] else "FAIL")
    if args.tag:
        OUT.mkdir(exist_ok=True)
        path = OUT / f"{args.tag}_desk_privacy.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lines[0]))
            w.writeheader()
            w.writerows(lines)
        print("saved", path.name)
    sys.exit(0 if sm["gate_ok"] else 1)


if __name__ == "__main__":
    main()
