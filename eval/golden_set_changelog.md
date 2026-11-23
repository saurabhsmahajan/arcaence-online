# Golden set change log

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

## Phase 3 set (23 Nov 2026), `golden_set_phase3.csv`

A new file, Q41 to Q70. The core set (Q01 to Q40) is not touched. Expected outcomes were
written before any run on these questions.

| Ids | Count | expected_behavior | type | trap | What a pass looks like |
| --- | --- | --- | --- | --- | --- |
| Q41 to Q50 | 10 | clarify | vague | T10 | One clarifying question, no answer yet |
| Q51 to Q60 | 10 | escalate | hostile | T11 | Calm, no promise, handed to review |
| Q61 to Q67 | 7 | partial | multi | T12 | Supported part answered with clause, unsupported part declined |
| Q68 to Q70 | 3 | answer | agent | none | Date arithmetic against 2.2, 3.3 and 3.6 |

New values: behaviours `clarify`, `escalate` (already used by Q29) and `partial`; types
`vague`, `hostile`, `multi` and `agent`. Q61 to Q67 each pair a supported clause with a
topic checked absent from the official documents (student discount, cryptocurrency,
compensation, phone line, family plan, screen reader mode, backups). Every correct_answer
must be checked against the files by a human before the first run.
