"""Run the attack harness. From the mcp folder:
    uv run python attacks/run_attacks.py 2>$null                       (all families, results only)
    uv run python attacks/run_attacks.py A F 2>$null                   (only families A and F)
    uv run python attacks/run_attacks.py --report ..\\docs\\evidence\\g2-attack-run.md 2>$null   (also save a report)
Exit code: 0 all blocked, 1 any FAIL, 2 none failed but some were skipped."""
import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
import family_a  # noqa: E402,F401  (importing a family registers its attacks)
import family_b  # noqa: E402,F401
import family_c  # noqa: E402,F401
import family_d  # noqa: E402,F401
import family_e  # noqa: E402,F401
import family_f  # noqa: E402,F401

FAMILY_NAMES = {"A": "Privilege and surface", "B": "Injection and malformed input", "C": "Money abuse",
                "D": "Irreversible and privacy actions", "E": "Data exposure", "F": "Untrusted text"}


def git_state() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=harness.MCP_DIR, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=harness.MCP_DIR, capture_output=True, text=True).stdout.strip()
        return f"{commit}{' plus uncommitted changes' if dirty else ''}" if commit else "unknown"
    except OSError:
        return "unknown"


def cell(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def write_report(path: Path, results, counts, selected) -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist).strftime("%d %b %Y, %H:%M IST")
    verdict = "G2 met" if not counts[harness.FAIL] and not counts[harness.SKIP] and not selected else "G2 not shown by this run"
    lines = [
        "# G2 attack harness run", "",
        f"Run: {now} · code commit: {git_state()} · attacks: {len(results)} · result: **{verdict}**", "",
        "Gate G2 asks for a recorded run in which every known attack on the MCP servers is blocked. "
        "The harness starts the real reader, writer and policy servers over stdio and sends hostile input only. "
        "An attack passes only if the answer is a refusal **and** the money and privacy tables are unchanged.", "",
        "| Result | Count |", "| --- | --- |",
        f"| Blocked (PASS) | {counts[harness.PASS]} |", f"| Known gap, behaved as documented (KNOWN) | {counts[harness.KNOWN]} |",
        f"| Failed | {counts[harness.FAIL]} |", f"| Skipped | {counts[harness.SKIP]} |", "",
    ]
    if selected:
        lines += [f"Only families {', '.join(sorted(selected))} were run, so this is not a full G2 run.", ""]
    for fam in sorted({a.id[0] for a, _, _ in results}):
        lines += [f"## {fam}. {FAMILY_NAMES.get(fam, fam)}", "", "| ID | Result | Attack | Tests | What happened |", "| --- | --- | --- | --- | --- |"]
        for a, status, detail in results:
            if a.id[0] == fam:
                lines.append(f"| {a.id} | {status} | {cell(a.name, 100)} | {cell(a.adr, 30)} | {cell(detail)} |")
        lines.append("")
    known = [a for a, s, _ in results if s == harness.KNOWN]
    if known:
        lines += ["## Known gaps", "",
                  "A known gap is something the attack can do today, accepted and recorded instead of hidden: "
                  + ", ".join(a.id for a in known) + ". The server does not know who is calling; the desk agents hold the "
                  "customer's identity. Binding an agent to one customer is open work.", ""]
    lines += ["## What this run does not cover", "",
              "- Many small refunds under the cap, and expired tokens: proven in `test_policy.py` and `test_actions.py`, because proving them over the wire needs a real commit.",
              "- Rate limits and load: there are none yet (planned for 28 Nov).",
              "- Attacks the catalogue does not list. A passing run shows the listed attacks are blocked, not that no attack exists.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> int:
    args = sys.argv[1:]
    report = None
    if "--report" in args:
        i = args.index("--report")
        report = Path(args[i + 1])
        del args[i:i + 2]
    select = {a.upper() for a in args} or None
    out = asyncio.run(harness.run(select))
    counts = {harness.PASS: 0, harness.FAIL: 0, harness.KNOWN: 0, harness.SKIP: 0}
    for a, status, detail in out["results"]:
        counts[status] += 1
        print(f"{status:<5} {a.id:<4} {a.name} ({a.adr})\n        {detail}")
    print(f"\n{counts[harness.PASS]} blocked, {counts[harness.KNOWN]} known gaps, "
          f"{counts[harness.FAIL]} FAILED, {counts[harness.SKIP]} skipped")
    if report:
        write_report(report, out["results"], counts, select)
        print(f"report written to {report}")
    if counts[harness.FAIL]:
        return 1
    return 2 if counts[harness.SKIP] else 0


if __name__ == "__main__":
    sys.exit(main())
