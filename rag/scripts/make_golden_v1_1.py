"""Build eval/golden_set_core_v1_1.csv from v1 with three reviewed changes.

v1 is never edited. Each change is guarded: the script stops if a v1 cell is not
what the change log says it was, so it cannot silently edit the wrong row.
Run from the repo root:  uv run python rag\\scripts\\make_golden_v1_1.py
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "eval" / "golden_set_core.csv"
DST = ROOT / "eval" / "golden_set_core_v1_1.csv"
LOG = ROOT / "eval" / "golden_set_changelog.md"

CHANGES = [
    ("Q24", "correct_answer",
     "Non-payment, suspected fraud, or breach of the Terms.",
     "An account may be suspended for non-payment, suspected fraud, or breach of the "
     "Terms (clause 6.2), and while a dispute with your bank is open (clause 4.4)."),
    ("Q24", "authoritative_source",
     "01_terms_of_service_v3.md s6.2",
     "01_terms_of_service_v3.md s6.2 and s4.4"),
    ("Q28", "must_not_cite_files", "02,05", "02,03,05"),
    ("Q29", "authoritative_source",
     "01_terms_of_service_v3.md s2.2 + regulation text (to be read)",
     "01_terms_of_service_v3.md s2.2 + 10_digital_goods_consumer_rights_act_fictional.md "
     "s2.2, s3.1, s3.2"),
]

CHANGELOG = """# Golden set change log

v1 (`golden_set_core.csv`) is never edited. Each later version is a new file, and every
scorer run records which file it used.

## v1.1 (17 Nov 2026), `golden_set_core_v1_1.csv`

Three reviewed changes. None was made to rescue a result: each was logged before the
re-run (Q24 on 15 Nov, Q28 and Q29 on 17 Nov).

| Question | Column | v1 | v1.1 | Why |
| --- | --- | --- | --- | --- |
| Q24 | correct_answer | Non-payment, suspected fraud, or breach of the Terms. | An account may be suspended for non-payment, suspected fraud, or breach of the Terms (clause 6.2), and while a dispute with your bank is open (clause 4.4). | The official terms give a fourth reason in clause 4.4. A correct answer that mentioned it was judged wrong against the v1 reference. |
| Q24 | authoritative_source | 01_terms_of_service_v3.md s6.2 | 01_terms_of_service_v3.md s6.2 and s4.4 | Both clauses carry the answer. |
| Q28 | must_not_cite_files | 02,05 | 02,03,05 | The policy review meeting notes (03) state the 14-day window and are not an official source. They were missing from the forbidden list. |
| Q29 | authoritative_source | 01_terms_of_service_v3.md s2.2 + regulation text (to be read) | 01_terms_of_service_v3.md s2.2 + 10_digital_goods_consumer_rights_act_fictional.md s2.2, s3.1, s3.2 | The regulation text now exists as a synthetic statute in the corpus (ADR-030). Q29 stays `escalate` and out of the scorer until the agents exist. |

Effect on results: only Q24's judge verdict and Q28's forbidden-citation check can change.
Results scored against v1 stay valid and are not re-scored. A comparison that includes Q24
across versions must say which reference it used.
"""


def main():
    with open(SRC, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    by_id = {r["id"]: r for r in rows}
    for qid, col, old, new in CHANGES:
        cell = by_id[qid][col].strip()
        if cell != old:
            raise SystemExit(f"{qid}.{col} is {cell!r}, expected {old!r}; nothing written.")
        by_id[qid][col] = new
    with open(DST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    LOG.write_text(CHANGELOG, encoding="utf-8", newline="\n")
    print(f"Wrote {DST.name} ({len(rows)} rows, {len(CHANGES)} cells changed) and {LOG.name}")


if __name__ == "__main__":
    main()
