"""Runs the Phase 3 golden set through the desk pipeline (or the old rag_on path) and scores it.

  uv run python desk_scorer.py --pipeline rag_on --tag p3_rag_on      # the "before" baseline
  uv run python desk_scorer.py --pipeline desk   --tag p3_desk        # the desk pipeline
  uv run python desk_scorer.py --pipeline desk --tag ci --baseline ..\\eval\\results\\desk_baseline.json
  uv run python desk_scorer.py --make-spotcheck p3_desk --run 2       # blind label file + key
  uv run python desk_scorer.py --score-spotcheck ..\\eval\\results\\p3_desk_spotcheck_blind.csv

Checks are deterministic (see desk_scoring.py). Two judges, both recorded:
  tone judge        calm or not_calm, for clarify, escalate and partial answers (tone only)
  correctness judge correct, wrong or abstained, for 'answer' rows only (the three date questions,
                    where the outcome is date arithmetic); the same judge as the older phases
A fixed sample of judge verdicts is written to a spot-check file for you to label yourself.
"""
import argparse
import csv
import json
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

from desk_scoring import gate, score_deterministic, summarize

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
OUT = EVAL / "results"

TONE_SYSTEM = """You judge the TONE of a customer support reply. Judge tone only, not facts.
Reply with exactly one word: calm or not_calm.
calm     = polite, steady, no blame, no sarcasm, no pressure, no scolding.
not_calm = rude, defensive, blaming, sarcastic, panicked or pushy."""


def tone_judge(client, model, question, answer):
    msg = client.messages.create(
        model=model, max_tokens=2000, system=TONE_SYSTEM,
        messages=[{"role": "user", "content": f"Customer: {question}\n\nReply: {answer}\n\nOne word:"}])
    text = "".join(b.text for b in msg.content if b.type == "text").strip().lower()
    return "not_calm" if "not_calm" in text or "not calm" in text else ("calm" if "calm" in text else "unparsed")


def run_pipeline(pipeline, question):
    if pipeline == "desk":
        from desk import desk_answer
        return desk_answer(question)
    from answer import answer_question
    r = answer_question(question, "rag_on")
    return {"behavior": "refuse" if r["refused"] else "answer", "answer": r["answer"],
            "citations": r["citations"], "problems": r["problems"] or [],
            "handoff": {"needed": False, "reason": ""}, "label": "n/a",
            "attempts": r.get("attempts", "")}


def make_spotcheck(tag, run, n=20):
    """Blind sample: model-written rows only (clarify, partial, answer) from one run.
    Escalate rows are one fixed template, so a judge verdict on them says nothing.
    The label file has no judge verdict; verdicts go in a separate key file."""
    runs = list(csv.DictReader(open(OUT / f"{tag}_runs.csv", newline="", encoding="utf-8-sig")))
    pool = [r for r in runs if r["run"] == str(run) and r["judge_kind"]
            and r["judge_verdict"] and r["expected"] != "escalate"]
    random.Random(11).shuffle(pool)
    pool = pool[:n]
    path = OUT / f"{tag}_spotcheck_blind.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "kind", "question", "answer", "human_label"])
        for r in pool:
            w.writerow([r["id"], r["judge_kind"], r["question"], r["answer"], ""])
    with open(OUT / f"{tag}_spotcheck_blind_key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "kind", "judge_verdict"])
        for r in pool:
            w.writerow([r["id"], r["judge_kind"], r["judge_verdict"]])
    print(f"Wrote {len(pool)} rows to {path.name} (verdicts are in the _key file; do not open it)")


def score_spotcheck(path):
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8-sig")))
    if rows and "judge_verdict" not in rows[0]:
        key = {(k["id"], k["kind"]): k["judge_verdict"] for k in csv.DictReader(
            open(Path(path).with_name(Path(path).stem + "_key.csv"), newline="", encoding="utf-8-sig"))}
        for r in rows:
            r["judge_verdict"] = key[(r["id"], r["kind"])]
    done = [r for r in rows if r["human_label"].strip()]
    skipped = len(rows) - len(done)
    if not done:
        print("No human_label values filled in yet.")
        return 1
    diff = [r for r in done if r["human_label"].strip().lower() != r["judge_verdict"].strip().lower()]
    rate = len(diff) / len(done)
    lines = [f"Judge spot-check: {len(done)} labelled ({skipped} skipped), "
             f"{len(diff)} disagreements = {rate:.0%}"]
    for r in diff:
        lines.append(f"- {r['id']} ({r['kind']}): judge={r['judge_verdict']} human={r['human_label']}")
    text = "\n".join(lines)
    print(text)
    Path(path).with_suffix(".result.md").write_text(text + "\n", encoding="utf-8")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", choices=["desk", "rag_on"], default="desk")
    ap.add_argument("--golden", default="golden_set_phase3.csv")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--tag", default="p3_desk")
    ap.add_argument("--baseline", default="", help="baseline json; exit 1 if the unsupported-claim rate rose")
    ap.add_argument("--write-baseline", default="", help="write this run's summary as a baseline json")
    ap.add_argument("--score-spotcheck", default="")
    ap.add_argument("--make-spotcheck", default="", help="tag of an existing run to sample from")
    ap.add_argument("--run", type=int, default=2, help="which run to sample (with --make-spotcheck)")
    args = ap.parse_args()
    if args.make_spotcheck:
        make_spotcheck(args.make_spotcheck, args.run)
        sys.exit(0)
    if args.score_spotcheck:
        sys.exit(score_spotcheck(args.score_spotcheck))

    import anthropic
    from scorer import JUDGE_MODEL, judge as fact_judge, load_doc_map
    client = anthropic.Anthropic()
    prefix_to_doc, _known = load_doc_map()
    golden = list(csv.DictReader(open(EVAL / args.golden, newline="", encoding="utf-8-sig")))
    print(f"Pipeline: {args.pipeline}. Golden set: {args.golden}. "
          f"{len(golden)} questions x {args.runs} runs.\n")

    rows = []
    for q in golden:
        forbidden = {prefix_to_doc[p.strip()] for p in q["must_not_cite_files"].split(",")
                     if p.strip() in prefix_to_doc}
        for run in range(1, args.runs + 1):
            try:
                res = run_pipeline(args.pipeline, q["question"])
                det = score_deterministic(q, res, forbidden, prefix_to_doc)
                kind, verdict = "", ""
                if q["expected_behavior"] == "answer":
                    kind, verdict = "correctness", fact_judge(q["question"], q["correct_answer"], res["answer"])
                    passed = det["pass_det"] and verdict == "correct"
                else:
                    passed = det["pass_det"]
                    if q["expected_behavior"] in ("clarify", "escalate", "partial"):
                        kind, verdict = "tone", tone_judge(client, JUDGE_MODEL, q["question"], res["answer"])
                row = {"id": q["id"], "expected": q["expected_behavior"], "run": run,
                       "label": res.get("label", ""), "behavior": res["behavior"],
                       "passed": passed, "unsupported": det["unsupported"],
                       "judge_kind": kind, "judge_verdict": verdict,
                       "answer": res["answer"].replace("\n", " ")[:600], "question": q["question"]}
            except Exception as exc:
                row = {"id": q["id"], "expected": q["expected_behavior"], "run": run, "label": "",
                       "behavior": "error", "passed": False, "unsupported": [],
                       "judge_kind": "", "judge_verdict": "", "answer": f"ERROR: {exc}",
                       "question": q["question"]}
            rows.append(row)
            print(f"{row['id']} run{run} expected={row['expected']:8} got={row['behavior']:8} "
                  f"pass={row['passed']} unsupported={row['unsupported'] or '-'} "
                  f"{row['judge_kind']}={row['judge_verdict'] or '-'}")

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{args.tag}_runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({**r, "unsupported": "; ".join(r["unsupported"])})

    s = summarize(rows)
    s.update({"pipeline": args.pipeline, "golden": args.golden, "runs": args.runs,
              "errors": sum(r["behavior"] == "error" for r in rows),
              "tone_not_calm": sum(r["judge_kind"] == "tone" and r["judge_verdict"] == "not_calm" for r in rows),
              "correctness_wrong": sum(r["judge_kind"] == "correctness" and r["judge_verdict"] == "wrong" for r in rows)})
    (OUT / f"{args.tag}_summary.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    if args.write_baseline:
        Path(args.write_baseline).write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")

    judged = [r for r in rows if r["run"] == 1 and r["judge_kind"] and r["judge_verdict"]]
    random.Random(7).shuffle(judged)
    with open(OUT / f"{args.tag}_spotcheck.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "kind", "question", "answer", "judge_verdict", "human_label"])
        for r in judged[:20]:
            w.writerow([r["id"], r["judge_kind"], r["question"], r["answer"], r["judge_verdict"], ""])

    print("\n" + json.dumps(s, indent=2))
    print(f"\nSaved {args.tag}_runs.csv, {args.tag}_summary.json, {args.tag}_spotcheck.csv in eval/results")
    if s["errors"]:
        print(f"WARNING: {s['errors']} rows errored; fix before trusting this run.")
        sys.exit(2)
    if args.baseline:
        ok, msg = gate(s, json.load(open(args.baseline)))
        print("GATE: " + ("PASS - " if ok else "FAIL - ") + msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
