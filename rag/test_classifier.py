"""Scores the classifier against the golden sets. Run from the rag folder.

Truth for each question comes from its `type` column:
vague -> vague, hostile -> hostile, everything else (normal, multi) -> answer path.
Normal and multi share one answering path (see desk.py), so telling them apart is
reported but does not gate. Q29 and Q30 are left out (they need a human handoff or
access control, built later). Use --holdout for eval/classifier_holdout.csv.

Gate (printed, exit code 1 if broken):
  - no message that should be answered is sent to vague or hostile (that changes behaviour)
  - at least 90% of the vague and hostile messages get the right label
The classifier is sampled, not deterministic: Q08 was labelled multi in 3 of 10 repeated
calls and Q42 vague in 6 of 10. Expect an occasional miss on a borderline message and
re-run before reading anything into a single failure.
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from classifier import LABELS, classify

EVAL = Path(__file__).resolve().parent.parent / "eval"
FILES = ["golden_set_core_v1_1.csv", "golden_set_phase3.csv"]
SKIP = {"Q29", "Q30"}
TRUTH = {"vague": "vague", "hostile": "hostile", "multi": "multi"}  # holdout truth uses the same words


def load(holdout):
    if holdout:
        with open(EVAL / "classifier_holdout.csv", newline="", encoding="utf-8-sig") as f:
            return [{"id": r["id"], "question": r["question"], "type": r["truth"]}
                    for r in csv.DictReader(f)]
    rows = []
    for name in FILES:
        with open(EVAL / name, newline="", encoding="utf-8-sig") as f:
            rows += [q for q in csv.DictReader(f) if q["id"] not in SKIP]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true",
                    help="score eval/classifier_holdout.csv instead of the golden sets")
    rows = load(ap.parse_args().holdout)
    matrix = Counter()
    misses = []
    for q in rows:
        truth = TRUTH.get(q["type"], "normal")
        got = classify(q["question"])
        matrix[(truth, got["label"])] += 1
        if got["label"] != truth:
            misses.append((q["id"], truth, got["label"], q["question"]))
        print(f"{q['id']} truth={truth:8} got={got['label']:8} {got['fallback_reason']}")

    print("\nConfusion (rows = truth, columns = got)")
    print("truth".ljust(10) + "".join(l.ljust(9) for l in LABELS))
    for t in LABELS:
        print(t.ljust(10) + "".join(str(matrix[(t, g)]).ljust(9) for g in LABELS))
    if misses:
        print("\nMisses")
        for m in misses:
            print(f"  {m[0]} truth={m[1]} got={m[2]}: {m[3]}")

    answer = lambda l: "answer" if l in ("normal", "multi") else l
    path = Counter()
    for (truth, got), n in matrix.items():
        path[(answer(truth), answer(got))] += n
    diverted = path[("answer", "vague")] + path[("answer", "hostile")]
    hard_total = sum(path[(t, g)] for t in ("vague", "hostile") for g in ("answer", "vague", "hostile"))
    hard_right = path[("vague", "vague")] + path[("hostile", "hostile")]
    rate = hard_right / hard_total if hard_total else 0
    split_total = sum(matrix[(t, g)] for t in ("normal", "multi") for g in ("normal", "multi"))
    split_right = matrix[("normal", "normal")] + matrix[("multi", "multi")]
    ok = diverted == 0 and rate >= 0.9
    print(f"\nmessages to be answered but sent to vague or hostile: {diverted} (must be 0)")
    print(f"vague/hostile correct: {hard_right}/{hard_total} = {rate:.0%} (must be >= 90%)")
    print(f"normal vs multi told apart (information only, not gated): {split_right}/{split_total}")
    print("CLASSIFIER GATE: " + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
