"""Golden-set scorer: runs each question through plain / rag_off / rag_on and grades it.

Two independent verdicts per answer:
  1. Code checks: forbidden documents cited, verifier problems.
  2. Judge model: correct / wrong / abstained against the reference answer.
"""
import argparse
import re
import csv
import os
from collections import defaultdict
from pathlib import Path

import anthropic
import psycopg
from dotenv import load_dotenv

from answer import CITE_RE, answer_question

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "eval" / "golden_set_core.csv"
OUT_DIR = ROOT / "eval" / "results"
JUDGE_MODEL = "claude-sonnet-5-5"
MODES = ["plain", "rag_off", "rag_on"]
NOT_SCOREABLE = {"Q29", "Q30"}  # need a human handoff / access control, built in later phases

JUDGE_SYSTEM = """You grade answers from a customer support assistant against a reference answer.
Reply with exactly one word: correct, wrong or abstained.

correct   = the answer states the same facts as the reference. Wording may differ and harmless
            extra detail is fine. Any figure, time period, currency or yes/no that contradicts
            the reference makes it wrong.
abstained = the answer declines, or says the information is not available, and asserts nothing
            else as the answer.
wrong     = the answer asserts something that contradicts the reference or is unsupported.

If the reference says the matter is not covered by the official documents, then an answer that
states a price, confirms a discount, or otherwise invents an answer is wrong. An answer that
says it is not covered is correct."""

client = anthropic.Anthropic()


def judge(question, reference, answer):
    prompt = (
        f"Question: {question}\n\nReference answer: {reference}\n\n"
        f"Assistant's answer: {answer}\n\nOne word:"
    )
    msg = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=2000,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip().lower()
    m = re.search(r"\b(incorrect|correct|wrong|abstained)\b", text)
    return ("wrong" if m.group(1) == "incorrect" else m.group(1)) if m else "unparsed"


def load_doc_map():
    """file number prefix ('02') -> doc_id, read from the documents table."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute("select doc_id, filename from documents").fetchall()
    return {fn[:2]: doc_id for doc_id, fn in rows}, {doc_id for doc_id, _ in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0, help="only the first N scoreable questions")
    args = ap.parse_args()

    prefix_to_doc, known_docs = load_doc_map()
    with open(GOLDEN, newline="", encoding="utf-8-sig") as f:
        golden = list(csv.DictReader(f))

    scoreable = [q for q in golden if q["id"] not in NOT_SCOREABLE]
    skipped = [q["id"] for q in golden if q["id"] in NOT_SCOREABLE]
    if args.limit:
        scoreable = scoreable[: args.limit]
    expect_abstain = {q["id"] for q in scoreable if q["expected_behavior"] == "refuse"}
    print(f"Scoring {len(scoreable)} questions x {len(MODES)} modes x {args.runs} runs")
    print(f"Not scoreable yet: {skipped}")
    print(f"Expected to abstain: {sorted(expect_abstain)}\n")

    rows = []
    for q in scoreable:
        forbidden = {
            prefix_to_doc[p.strip()]
            for p in q["must_not_cite_files"].split(",")
            if p.strip() in prefix_to_doc
        }
        for mode in MODES:
            for run in range(1, args.runs + 1):
                try:
                    res = answer_question(q["question"], mode)
                    answer = res["answer"] or ""
                    problems = list(res["problems"] or [])
                    verdict = judge(q["question"], q["correct_answer"], answer)
                except Exception as exc:  # API or DB hiccup: record, keep going
                    answer, problems, verdict = f"ERROR: {exc}", [], "error"

                cited = {m.group(1) for m in CITE_RE.finditer(answer)} & known_docs
                hit = sorted(cited & forbidden)
                abstain_ok = q["id"] in expect_abstain and verdict == "abstained"
                outcome_ok = verdict == "correct" or abstain_ok
                if mode == "plain":
                    # plain mode has no sources, so only the judge applies
                    passed = outcome_ok
                    hit, problems = [], []
                else:
                    if abstain_ok:
                        problems = []
                    passed = outcome_ok and not hit and not problems

                rows.append({
                    "id": q["id"], "type": q["type"], "mode": mode, "run": run,
                    "verdict": verdict, "passed": passed,
                    "forbidden_cited": ";".join(hit),
                    "verifier_problems": " | ".join(problems),
                    "answer": answer.replace("\n", " ")[:600],
                })
                print(f"{q['id']} {mode:8} run{run} verdict={verdict:9} "
                      f"forbidden={hit or '-'} problems={len(problems)} pass={passed}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs_path = OUT_DIR / "baseline_runs.csv"
    with open(runs_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    lines = ["# Baseline results", "",
             f"Questions scored: {len(scoreable)}. Runs per question: {args.runs}. "
             f"Not scoreable yet: {', '.join(skipped)}. Judge: {JUDGE_MODEL}.", "",
             "| Mode | All | Normal | Trap | Wrong | Abstained | Forbidden cited | Verifier problems |",
             "|---|---|---|---|---|---|---|---|"]
    for mode in MODES:
        mr = [r for r in rows if r["mode"] == mode]

        def rate(sel):
            sel = list(sel)
            return f"{sum(r['passed'] for r in sel)}/{len(sel)}"

        lines.append(
            f"| {mode} | {rate(mr)} | {rate(r for r in mr if r['type']=='normal')} "
            f"| {rate(r for r in mr if r['type']=='trap')} "
            f"| {sum(r['verdict']=='wrong' for r in mr)} "
            f"| {sum(r['verdict']=='abstained' for r in mr)} "
            f"| {sum(bool(r['forbidden_cited']) for r in mr)} "
            f"| {sum(bool(r['verifier_problems']) for r in mr)} |"
        )
    by_key = defaultdict(set)
    for r in rows:
        by_key[(r["id"], r["mode"])].add(r["passed"])
    flaky = sorted({k[0] + "/" + k[1] for k, v in by_key.items() if len(v) > 1})
    lines += ["", f"Questions whose result changed between runs: {len(flaky)}", ""]
    lines += [f"- {k}" for k in flaky]
    summary_path = OUT_DIR / "baseline_summary.md"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nSaved {runs_path} and {summary_path}")


if __name__ == "__main__":
    main()
