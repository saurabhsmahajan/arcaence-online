import csv
from pathlib import Path

RES = Path(__file__).resolve().parent.parent.parent / "eval" / "results"
MODES = ["plain", "rag_off", "rag_on"]


def load(name):
    with open(RES / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


baseline = load("baseline_runs.csv")
after = load("after_router_fix_runs.csv")
recheck = load("recheck_q27_runs.csv") + load("recheck_q28_runs.csv")
redone = {r["id"] for r in recheck}
after = [r for r in after if r["id"] not in redone] + recheck

with open(RES / "after_runs_merged.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(after[0].keys()))
    w.writeheader()
    w.writerows(after)


def stats(rows, mode, qtype=None):
    sel = [r for r in rows if r["mode"] == mode and (qtype is None or r["type"] == qtype)]
    return sum(r["passed"] == "True" for r in sel), len(sel)


def frac(p):
    return f"{p[0]}/{p[1]}"


errors = sum(r["verdict"] == "error" for r in baseline + after)
lines = [
    "# Baseline vs after router fix",
    "",
    f"Error rows remaining in either run: {errors}. Q27 and Q28 rows in the 'after' set come from re-runs after an API outage.",
    "",
    "| Mode | Baseline | After | After: normal | After: trap | Wrong | Forbidden cited | Verifier problems |",
    "|---|---|---|---|---|---|---|---|",
]
for mode in MODES:
    ar = [r for r in after if r["mode"] == mode]
    lines.append(
        f"| {mode} | {frac(stats(baseline, mode))} | {frac(stats(after, mode))} "
        f"| {frac(stats(after, mode, 'normal'))} | {frac(stats(after, mode, 'trap'))} "
        f"| {sum(r['verdict'] == 'wrong' for r in ar)} "
        f"| {sum(bool(r['forbidden_cited']) for r in ar)} "
        f"| {sum(bool(r['verifier_problems']) for r in ar)} |"
    )
lines += ["", "Failing rag_on rows after the fix:", ""]
for r in after:
    if r["mode"] == "rag_on" and r["passed"] != "True":
        lines.append(f"- {r['id']} run{r['run']}: {r['verdict']}")
(RES / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
