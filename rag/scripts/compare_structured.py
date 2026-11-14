import csv
from pathlib import Path

RES = Path(__file__).resolve().parent.parent.parent / "eval" / "results"
MODES = ["plain", "rag_off", "rag_on"]


def load(name):
    with open(RES / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


baseline = load("baseline_runs.csv")
after = load("after_runs_merged.csv")
first = load("structured_v1_runs.csv")
rerun = load("structured_v1_rerun_runs.csv")
redone = {r["id"] for r in rerun}
structured = [r for r in first if r["id"] not in redone] + rerun

with open(RES / "structured_v1_merged_runs.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(structured[0].keys()))
    w.writeheader()
    w.writerows(structured)

errors = {name: sum(r["verdict"] == "error" for r in rows)
          for name, rows in [("baseline", baseline), ("after", after), ("structured", structured)]}
if any(errors.values()):
    raise SystemExit(f"Error rows remain, not comparing: {errors}")


def stats(rows, mode, qtype=None):
    sel = [r for r in rows if r["mode"] == mode and (qtype is None or r["type"] == qtype)]
    return f"{sum(r['passed'] == 'True' for r in sel)}/{len(sel)}"


def count(rows, mode, test):
    return sum(1 for r in rows if r["mode"] == mode and test(r))


lines = [
    "# Baseline vs after router fix vs structured answers (v1)",
    "",
    "Error rows in any run: 0. Structured run = structured_v1 with Q23, Q31, Q32, Q33 re-run after a local network outage and merged by id.",
    "",
    "| Mode | Baseline | After router fix | Structured | Structured: normal | Structured: trap | Wrong | Abstained | Forbidden cited | Verifier problems |",
    "|---|---|---|---|---|---|---|---|---|---|",
]
for mode in MODES:
    lines.append(
        f"| {mode} | {stats(baseline, mode)} | {stats(after, mode)} | {stats(structured, mode)} "
        f"| {stats(structured, mode, 'normal')} | {stats(structured, mode, 'trap')} "
        f"| {count(structured, mode, lambda r: r['verdict'] == 'wrong')} "
        f"| {count(structured, mode, lambda r: r['verdict'] == 'abstained')} "
        f"| {count(structured, mode, lambda r: bool(r['forbidden_cited']))} "
        f"| {count(structured, mode, lambda r: bool(r['verifier_problems']))} |"
    )
lines += ["", "Failing rag_on rows (structured):", ""]
for r in structured:
    if r["mode"] == "rag_on" and r["passed"] != "True":
        lines.append(f"- {r['id']} run{r['run']}: {r['verdict']}")
(RES / "comparison_structured.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))